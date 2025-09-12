from __future__ import annotations
import json, os, random, sys, time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, Optional, Tuple
import pygame
import math

# ========= IMAGE LOADER (cache) =========
class ImageStore:
    def __init__(self):
        self.cache: dict[str, pygame.Surface] = {}

    def load(self, path: str, *, allow_alpha: bool = True) -> Optional[pygame.Surface]:
        if not path:
            return None
        if path in self.cache:
            return self.cache[path]
        try:
            img = pygame.image.load(path)
            img = img.convert_alpha() if allow_alpha else img.convert()
            self.cache[path] = img
            return img
        except Exception:
            return None

    def clear(self):
        self.cache.clear()

IMAGES = ImageStore()

# ========= CONFIG =========
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULT_CFG = {
    "pins":       {"CIRCLE": 17, "CROSS": 27, "SQUARE": 22, "TRIANGLE": 23},
    "display":    {"fullscreen": True, "fps": 60, "windowed_size": [720, 1280]},
    "speedup":    {"target_time_initial": 3, "target_time_min": 0.45, "target_time_step": -0.03},
    "timed":      {"duration": 60.0, "rule_bonus": 5.0},
    "rules":      {"every_hits": 5, "banner_sec": 2.0},
    "lives":      3,
    "audio":      {"music": "assets/music.ogg", "volume": 0.5},
    "images":     {
        "background": "assets/images/bg.png",
        "symbol_circle": "assets/images/circle.png",
        "symbol_cross": "assets/images/cross.png",
        "symbol_square": "assets/images/square.png",
        "symbol_triangle": "assets/images/triangle.png",
        "arrow": "assets/images/arrow.png",
    },
    "highscore": 0,
}

def _deepcopy(obj): return json.loads(json.dumps(obj))

def _merge(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v
    return dst

def _sanitize_cfg(cfg: dict) -> dict:
    s = cfg["speedup"]
    s["target_time_initial"] = float(max(0.2, min(10.0, s["target_time_initial"])) )
    s["target_time_min"]     = float(max(0.1, min(s["target_time_initial"], s["target_time_min"])) )
    s["target_time_step"]    = float(max(-1.0, min(1.0, s["target_time_step"])) )
    cfg["lives"]             = int(max(1, min(9, cfg["lives"])))
    cfg["audio"]["volume"]   = float(max(0.0, min(1.0, cfg["audio"]["volume"])))
    if "fps" in cfg["display"]:
        cfg["display"]["fps"] = int(max(30, min(240, cfg["display"]["fps"])))
    ws = cfg["display"].get("windowed_size", [720, 1280])
    if (isinstance(ws, (list, tuple)) and len(ws) == 2
        and all(isinstance(x, (int, float)) for x in ws)):
        w, h = int(ws[0]), int(ws[1])
        w = max(200, min(10000, w))
        h = max(200, min(10000, h))
        cfg["display"]["windowed_size"] = [w, h]
    else:
        cfg["display"]["windowed_size"] = [720, 1280]
    return cfg

def save_config(partial_cfg: dict):
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            base = json.load(f)
        if not isinstance(base, dict):
            base = {}
    except Exception:
        base = {}
    merged = _merge(base, partial_cfg)
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def load_config() -> dict:
    cfg = _deepcopy(DEFAULT_CFG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user = json.load(f)
        _merge(cfg, user)
    except FileNotFoundError:
        save_config(cfg)
    except Exception:
        pass
    return _sanitize_cfg(cfg)

CFG = load_config()

def _persist_windowed_size(width: int, height: int):
    try:
        CFG.setdefault("display", {})
        CFG["display"]["windowed_size"] = [int(width), int(height)]
        save_config({"display": {"windowed_size": CFG["display"]["windowed_size"]}})
    except Exception:
        pass

# ========= GPIO (optional) =========
GPIO_AVAILABLE = True
IS_WINDOWS = sys.platform.startswith("win")
try:
    from gpiozero import Button  # type: ignore
except Exception:
    GPIO_AVAILABLE = False

@dataclass
class Pins:
    CIRCLE: int
    CROSS: int
    SQUARE: int
    TRIANGLE: int

PINS = Pins(**CFG["pins"])

class InputQueue:
    def __init__(self):
        self._q = []
    def push(self, name: str):
        self._q.append(name)
    def pop_all(self):
        out = self._q[:]
        self._q.clear()
        return out

# ========= CONSTANTS =========
BG       = (8, 10, 12)
PAD      = (40, 44, 52)
PAD_HI   = (90, 200, 255)
PAD_GOOD = (60, 200, 120)
PAD_BAD  = (220, 80, 80)
INK      = (235, 235, 235)
ACCENT   = (255, 210, 90)

SYMBOL_COLORS = {
    "TRIANGLE": (0, 255, 0),
    "CIRCLE":   (255, 0, 0),
    "CROSS":    (0, 0, 255),
    "SQUARE":   (255, 215, 0),
}

PADDING = 0.06
GAP     = 0.04
FPS     = CFG["display"]["fps"]

TARGET_TIME_INITIAL   = CFG["speedup"]["target_time_initial"]
TARGET_TIME_MIN       = CFG["speedup"]["target_time_min"]
TARGET_TIME_STEP      = CFG["speedup"]["target_time_step"]
TIMED_DURATION        = CFG["timed"]["duration"]
RULE_EVERY_HITS       = CFG["rules"]["every_hits"]
RULE_BANNER_SEC       = CFG["rules"]["banner_sec"]
MAX_LIVES             = CFG["lives"]
ADDITIONAL_RULE_TIME  = float(CFG["timed"].get("rule_bonus", 5.0))

SYMBOL_BASE_SIZE_FACTOR  = 0.26
SYMBOL_ANIM_TIME         = 0.30
SYMBOL_ANIM_START_SCALE  = 0.20
SYMBOL_ANIM_OFFSET_Y     = 0.08

SHAKE_DURATION        = 0.12
SHAKE_AMPLITUDE_FACT  = 0.012
SHAKE_FREQ_HZ         = 18.0

UI_RADIUS = 8

SYMBOL_DRAW_THICKNESS         = 20
SYMBOL_SQUARE_RADIUS          = UI_RADIUS
SYMBOL_CIRCLE_RADIUS_FACTOR   = 0.32
SYMBOL_TRIANGLE_POINT_FACTOR  = 0.9
SYMBOL_CROSS_K_FACTOR         = 1.0

HUD_TOP_MARGIN_FACTOR = 0.02
HUD_SEPARATOR         = "   ·   "

# --- Glitch ---
GLITCH_DURATION = 0.20
GLITCH_PIXEL_FACTOR_MAX = 0.10
GLITCH_FREQ_HZ = 60.0

# --- Spawn anim ---
SYMBOL_SPAWN_ANIM_DURATION = 0.40
SYMBOL_SPAWN_GLITCH_DURATION = 0.02
SYMBOL_SPAWN_GLOW_MAX_ALPHA = 20
SYMBOL_SPAWN_GLOW_RADIUS_FACTOR = 1.15

# --- Timer bar ---
TIMER_BAR_WIDTH_FACTOR = 0.60
TIMER_BAR_HEIGHT       = 18
TIMER_BAR_MARGIN_TOP   = 10
TIMER_BAR_BG           = (40, 40, 50)
TIMER_BAR_FILL         = (90, 200, 255)
TIMER_BAR_BORDER       = (160, 180, 200)
TIMER_BAR_BORDER_W     = 2
TIMER_BAR_WARN_COLOR   = (255, 170, 80)
TIMER_BAR_CRIT_COLOR   = (220, 80, 80)
TIMER_BAR_WARN_TIME    = 0.33
TIMER_BAR_CRIT_TIME    = 0.15
TIMER_BAR_BORDER_RADIUS= UI_RADIUS
TIMER_BAR_TEXT_COLOR   = INK
TIMER_FONT_SIZE        = 48

# --- Rule banner ---
RULE_BANNER_ICON_SIZE_FACTOR = 0.22
RULE_BANNER_GAP_FACTOR       = 0.06
RULE_BANNER_IN_SEC      = 0.35
RULE_BANNER_HOLD_SEC    = 1.20
RULE_BANNER_OUT_SEC     = 0.35
RULE_BANNER_TOTAL_SEC   = RULE_BANNER_IN_SEC + RULE_BANNER_HOLD_SEC + RULE_BANNER_OUT_SEC
RULE_PANEL_W_FACTOR     = 0.78
RULE_PANEL_H_FACTOR     = 0.32
RULE_PANEL_BG           = (22, 26, 34, 110)  # RGBA
RULE_PANEL_BORDER       = (120, 200, 255)
RULE_PANEL_BORDER_W     = 3
RULE_PANEL_RADIUS       = 14
RULE_ICON_SIZE_FACTOR   = 0.17
RULE_ICON_GAP_FACTOR    = 0.04
RULE_ARROW_W            = 6
RULE_ARROW_COLOR        = (200, 220, 255)

# --- Screens ---
MENU_TITLE_Y_FACTOR   = 0.28
MENU_MODE_GAP         = 20
MENU_HINT_GAP         = 48
MENU_HINT2_EXTRA_GAP  = 12
OVER_TITLE_OFFSET_Y   = -60
OVER_SCORE_GAP1       = -10
OVER_SCORE_GAP2       = 26
OVER_INFO_GAP         = 60
SETTINGS_TITLE_Y_FACTOR       = 0.18
SETTINGS_LIST_Y_START_FACTOR  = 0.26
SETTINGS_ITEM_SPACING         = 14
SETTINGS_HELP_MARGIN_TOP      = 18
SETTINGS_HELP_GAP             = 6

# --- Aspect ---
ASPECT_RATIO            = (9, 16)
ASPECT_SNAP_MIN_SIZE    = (360, 640)
ASPECT_SNAP_TOLERANCE   = 0.0

# --- Fonts ---
FONT_PATH        = "assets/font/Orbitron-VariableFont_wght.ttf"
FONT_SIZE_SMALL  = 24
FONT_SIZE_MID    = 36
FONT_SIZE_BIG    = 48

# --- Audio ---
MUSIC_FADEOUT_MS = 800

# --- Window ---
WINDOWED_DEFAULT_SIZE = tuple(CFG.get("display", {}).get("windowed_size", (720, 1280)))
WINDOWED_FLAGS        = pygame.RESIZABLE

# --- GPIO ---
GPIO_PULL_UP      = True
GPIO_BOUNCE_TIME  = 0.05

# --- Keymap ---
KEYMAP: Dict[int, str] = {
    pygame.K_UP: "TRIANGLE", pygame.K_RIGHT: "CIRCLE",  pygame.K_LEFT: "SQUARE", pygame.K_DOWN: "CROSS",
    pygame.K_w:  "TRIANGLE", pygame.K_d:     "CIRCLE",  pygame.K_a:   "SQUARE", pygame.K_s:   "CROSS",
}

def init_gpio(iq: InputQueue):
    if IS_WINDOWS or not GPIO_AVAILABLE:
        return {}
    pins = {"CIRCLE": PINS.CIRCLE, "CROSS": PINS.CROSS, "SQUARE": PINS.SQUARE, "TRIANGLE": PINS.TRIANGLE}
    buttons = {name: Button(pin, pull_up=GPIO_PULL_UP, bounce_time=GPIO_BOUNCE_TIME) for name, pin in pins.items()}
    for name, btn in buttons.items():
        btn.when_pressed = (lambda n=name: iq.push(n))
    return buttons

# ========= ENUMS =========
class Symbol(Enum):
    TRIANGLE = auto()
    CIRCLE   = auto()
    SQUARE   = auto()
    CROSS    = auto()

SYMS = [s.name for s in Symbol]

class Mode(Enum):
    SPEEDUP = auto()
    TIMED   = auto()

class Scene(Enum):
    MENU     = auto()
    GAME     = auto()
    OVER     = auto()
    SETTINGS = auto()

# ========= DRAW HELPERS =========
def draw_symbol(surface: pygame.Surface, name: str, rect: pygame.Rect):
    path = CFG["images"].get(f"symbol_{name.lower()}")
    img = IMAGES.load(path)
    if not img:
        color = SYMBOL_COLORS.get(name, INK)
        thickness = SYMBOL_DRAW_THICKNESS
        cx, cy = rect.center
        w, h = rect.size
        r = min(w, h) * SYMBOL_CIRCLE_RADIUS_FACTOR
        if name == "CIRCLE":
            pygame.draw.circle(surface, color, (int(cx), int(cy)), int(r), thickness)
        elif name == "SQUARE":
            side = r * 1.6
            rr = pygame.Rect(0, 0, side, side); rr.center = rect.center
            pygame.draw.rect(surface, color, rr, thickness, border_radius=SYMBOL_SQUARE_RADIUS)
        elif name == "TRIANGLE":
            a = (cx, cy - r)
            b = (cx - r * SYMBOL_TRIANGLE_POINT_FACTOR, cy + r * SYMBOL_TRIANGLE_POINT_FACTOR)
            c = (cx + r * SYMBOL_TRIANGLE_POINT_FACTOR, cy + r * SYMBOL_TRIANGLE_POINT_FACTOR)
            pygame.draw.polygon(surface, color, [a, b, c], thickness)
        elif name == "CROSS":
            k = r * SYMBOL_CROSS_K_FACTOR
            pygame.draw.line(surface, color, (cx - k, cy - k), (cx + k, cy + k), thickness)
            pygame.draw.line(surface, color, (cx - k, cy + k), (cx + k, cy - k), thickness)
    else:
        img_w, img_h = img.get_size()
        scale = min(rect.width / img_w, rect.height / img_h)
        new_size = (int(img_w * scale), int(img_h * scale))
        scaled_img = pygame.transform.smoothscale(img, new_size)
        img_rect = scaled_img.get_rect(center=rect.center)
        surface.blit(scaled_img, img_rect)

def draw_arrow(surface: pygame.Surface, rect: pygame.Rect,
               color=RULE_ARROW_COLOR, width=RULE_ARROW_W):
    path = CFG.get("images", {}).get("arrow")
    img = IMAGES.load(path) if path else None
    if img:
        iw, ih = img.get_size()
        scale = min(rect.width / iw, rect.height / ih)
        new_size = (int(iw * scale), int(ih * scale))
        scaled = pygame.transform.smoothscale(img, new_size)
        r = scaled.get_rect(center=rect.center)
        surface.blit(scaled, r)
        return
    ax1 = rect.left + width
    ax2 = rect.right - width * 1.5
    ay  = rect.centery
    pygame.draw.line(surface, color, (ax1, ay), (ax2, ay), width)
    head_w = min(rect.width * 0.32, rect.height * 0.9)
    half_h = min(rect.height * 0.45, rect.width * 0.28)
    p1 = (ax2, ay); p2 = (ax2 - head_w, ay - half_h); p3 = (ax2 - head_w, ay + half_h)
    pygame.draw.polygon(surface, color, (p1, p2, p3), width)

# ========= GAME =========
class Game:
    def __init__(self, screen: pygame.Surface, mode: Mode = Mode.SPEEDUP):
        self.screen = screen
        self.mode: Mode = mode
        self.scene: Scene = Scene.MENU

        self.w, self.h = self.screen.get_size()
        self.clock = pygame.time.Clock()

        self.font       = pygame.font.Font(FONT_PATH, FONT_SIZE_SMALL)
        self.big        = pygame.font.Font(FONT_PATH, FONT_SIZE_BIG)
        self.mid        = pygame.font.Font(FONT_PATH, FONT_SIZE_MID)
        self.timer_font = pygame.font.Font(FONT_PATH, TIMER_FONT_SIZE)

        self.bg_img_raw = self._load_background()
        self.bg_img = None

        self._recompute_layout()
        self._rescale_background()

        # offscreen framebuffer
        self.fb = pygame.Surface((self.w, self.h), pygame.SRCALPHA)

        # gameplay state
        self.score = 0
        self.lives = MAX_LIVES
        self.target: Optional[str] = None
        self.target_deadline: Optional[float] = None
        self.target_time = TARGET_TIME_INITIAL
        self.hits_since_rule = 0
        self.rule: Optional[Tuple[str,str]] = None
        self.rule_banner_until = 0.0
        self.rule_banner_anim_start = 0.0
        self.pause_start = 0.0
        self.pause_until = 0.0
        self.shake_start = 0.0
        self.shake_until = 0.0
        self.symbol_spawn_time = 0.0
        self.time_left = TIMED_DURATION
        self._last_tick = 0.0
        self.highscore = int(CFG.get("highscore", 0))

        # glitch state
        self.glitch_active_until = 0.0
        self.glitch_start_time = 0.0

        # settings buffer (ekran Settings)
        self.settings_idx = 0
        self.settings = {
            "target_time_initial": float(CFG["speedup"]["target_time_initial"]),
            "target_time_step":    float(CFG["speedup"]["target_time_step"]),
            "target_time_min":     float(CFG["speedup"]["target_time_min"]),
            "lives":               int(CFG["lives"]),
            "volume":              float(CFG["audio"]["volume"]),
            "fullscreen":          bool(CFG["display"]["fullscreen"]),
            "timed_rule_bonus":    float(CFG["timed"].get("rule_bonus", 5.0)),
        }

        self.music_ok = False
        self._ensure_music()
        self.last_window_size = self.screen.get_size()

    # ----- utils -----
    def now(self) -> float: return time.time()

    def _ensure_framebuffer(self):
        self.fb = pygame.Surface((self.w, self.h), pygame.SRCALPHA)

    def _recompute_layout(self):
        self.w, self.h = self.screen.get_size()
        pad_w = (self.w * (1 - 2 * PADDING - GAP)) / 2
        pad_h = (self.h * (1 - 2 * PADDING - GAP)) / 2
        x1 = self.w * PADDING
        x2 = x1 + pad_w + self.w * GAP
        y1 = self.h * PADDING
        y2 = y1 + pad_h + self.h * GAP
        self.pads = {
            "TRIANGLE": pygame.Rect(x1, y1, pad_w, pad_h),
            "CIRCLE":   pygame.Rect(x2, y1, pad_w, pad_h),
            "SQUARE":   pygame.Rect(x1, y2, pad_w, pad_h),
            "CROSS":    pygame.Rect(x2, y2, pad_w, pad_h),
        }
        self._rescale_background()
        self._ensure_framebuffer()

    def _ensure_music(self):
        if self.music_ok:
            return
        try:
            pygame.mixer.init()
            if os.path.exists(CFG["audio"]["music"]):
                pygame.mixer.music.load(CFG["audio"]["music"])
                pygame.mixer.music.set_volume(float(CFG["audio"]["volume"]))
                self.music_ok = True
        except Exception:
            self.music_ok = False

    def trigger_shake(self):
        now = self.now()
        self.shake_start = now
        self.shake_until = now + SHAKE_DURATION

    def _load_background(self):
        path = CFG.get("images", {}).get("background") if isinstance(CFG.get("images"), dict) else None
        if not path or not os.path.exists(path):
            return None
        return IMAGES.load(path, allow_alpha=True)

    def _rescale_background(self):
        raw = getattr(self, "bg_img_raw", None)
        if not raw:
            self.bg_img = None
            return
        rw, rh = raw.get_size()
        sw, sh = self.w, self.h
        scale = max(sw / rw, sh / rh)        # cover
        new_size = (int(rw * scale), int(rh * scale))
        img = pygame.transform.smoothscale(raw, new_size)
        x = (img.get_width()  - sw) // 2
        y = (img.get_height() - sh) // 2
        self.bg_img = img.subsurface(pygame.Rect(x, y, sw, sh)).copy()

    def _set_display_mode(self, fullscreen: bool):
        if fullscreen:
            try:
                desktop_w, desktop_h = pygame.display.get_desktop_sizes()[0]
            except Exception:
                info = pygame.display.Info()
                desktop_w, desktop_h = info.current_w, info.current_h
            flags, size = pygame.NOFRAME, (desktop_w, desktop_h)  # borderless fullscreen
        else:
            size = WINDOWED_DEFAULT_SIZE
            flags = WINDOWED_FLAGS
        self.screen = pygame.display.set_mode(size, flags)
        self.last_window_size = self.screen.get_size()
        if not fullscreen:
            _persist_windowed_size(*self.last_window_size)
        self._recompute_layout()

    def _snap_to_aspect(self, width: int, height: int) -> Tuple[int, int]:
        target_w, target_h = ASPECT_RATIO
        ratio = target_w / target_h
        last_w, last_h = getattr(self, "last_window_size", (width, height))
        if ASPECT_SNAP_TOLERANCE > 0:
            r = width / max(1, height)
            if abs(r - ratio) <= ASPECT_SNAP_TOLERANCE * ratio:
                return max(ASPECT_SNAP_MIN_SIZE[0], width), max(ASPECT_SNAP_MIN_SIZE[1], height)
        dw = abs(width - last_w); dh = abs(height - last_h)
        if dw >= dh: height = int(round(width / ratio))
        else:        width  = int(round(height * ratio))
        width  = max(ASPECT_SNAP_MIN_SIZE[0], width)
        height = max(ASPECT_SNAP_MIN_SIZE[1], height)
        return width, height

    def handle_resize(self, width: int, height: int):
        if bool(CFG.get("display", {}).get("fullscreen", True)):
            return
        width, height = self._snap_to_aspect(width, height)
        self.screen = pygame.display.set_mode((width, height), WINDOWED_FLAGS)
        self.last_window_size = (width, height)
        _persist_windowed_size(width, height)
        self._recompute_layout()

    # ----- settings -----
    def settings_items(self):
        return [
            ("Initial time",  f"{self.settings['target_time_initial']:.2f}s", "target_time_initial"),
            ("Time step",     f"{self.settings['target_time_step']:+.2f}s/hit", "target_time_step"),
            ("Minimum time",  f"{self.settings['target_time_min']:.2f}s", "target_time_min"),
            ("Lives",         f"{int(self.settings['lives'])}", "lives"),
            ("Volume",        f"{self.settings['volume']:.2f}", "volume"),
            ("Fullscreen",    "ON" if self.settings['fullscreen'] else "OFF", "fullscreen"),
            ("High score",    f"{self.highscore}", None),
            ("Rule bonus",    f"{self.settings['timed_rule_bonus']:.1f}s", "timed_rule_bonus"),
        ]

    def settings_move(self, delta: int):
        items = self.settings_items()
        n, idx = len(items), self.settings_idx
        for _ in range(n):
            idx = (idx + delta) % n
            if items[idx][2] is not None:
                self.settings_idx = idx
                return
        self.settings_idx = 0

    def _settings_clamp(self):
        s = self.settings
        s["target_time_initial"] = max(0.2, min(10.0, float(s["target_time_initial"])))
        s["target_time_min"]     = max(0.1, min(float(s["target_time_initial"]), float(s["target_time_min"])) )
        s["target_time_step"]    = max(-1.0, min(1.0, float(s["target_time_step"])))
        s["lives"]               = max(1, min(9, int(s["lives"])))
        s["volume"]              = max(0.0, min(1.0, float(s["volume"])))
        s["timed_rule_bonus"]    = max(0.0, min(30.0, float(s["timed_rule_bonus"])))

    def apply_fullscreen_now(self):
        want_full = bool(self.settings.get("fullscreen", True))
        if want_full:
            self.screen = pygame.display.set_mode((0,0), pygame.FULLSCREEN)
        else:
            w, h = getattr(self, "last_window_size", None) or tuple(CFG.get("display", {}).get("windowed_size", WINDOWED_DEFAULT_SIZE))
            self.screen = pygame.display.set_mode((w, h), WINDOWED_FLAGS)
            _persist_windowed_size(*self.screen.get_size())
        self.last_window_size = self.screen.get_size()
        self._recompute_layout()

    def settings_adjust(self, delta: int):
        items = self.settings_items()
        key = items[self.settings_idx][2]
        if key is None:
            return
        if key == "fullscreen":
            self.settings["fullscreen"] = not self.settings["fullscreen"]
            self.apply_fullscreen_now()
            CFG["display"]["fullscreen"] = bool(self.settings["fullscreen"])
            save_config({"display": {"fullscreen": CFG["display"]["fullscreen"]}})
            return
        step = {
            "target_time_initial": 0.1,
            "target_time_step":    0.01,
            "target_time_min":     0.05,
            "lives":               1,
            "volume":              0.05,
            "timed_rule_bonus":    0.5,
        }.get(key, 0.0)
        if step == 0.0:
            return
        cur = self.settings[key]
        self.settings[key] = (cur + (step * delta)) if isinstance(cur, float) else (cur + delta)
        self._settings_clamp()
        if key == "volume" and self.music_ok:
            pygame.mixer.music.set_volume(float(self.settings["volume"]))

    def settings_reset_highscore(self):
        self.highscore = 0
        CFG["highscore"] = 0
        save_config({"highscore": 0})

    def open_settings(self):
        self.settings.update({
            "target_time_initial": float(CFG["speedup"]["target_time_initial"]),
            "target_time_step":    float(CFG["speedup"]["target_time_step"]),
            "target_time_min":     float(CFG["speedup"]["target_time_min"]),
            "lives":               int(CFG["lives"]),
            "volume":              float(CFG["audio"]["volume"]),
            "fullscreen":          bool(CFG["display"]["fullscreen"]),
            "timed_rule_bonus":    float(CFG["timed"].get("rule_bonus", 5.0)),
        })
        self.settings_idx = 0
        self.settings_move(0)
        self.scene = Scene.SETTINGS

    def settings_save(self):
        self._settings_clamp()
        s = self.settings
        CFG["speedup"].update({
            "target_time_initial": float(s["target_time_initial"]),
            "target_time_step":    float(s["target_time_step"]),
            "target_time_min":     float(s["target_time_min"]),
        })
        CFG["lives"] = int(s["lives"])
        CFG["audio"]["volume"] = float(s["volume"])
        CFG["display"]["fullscreen"] = bool(s["fullscreen"])
        CFG["timed"]["rule_bonus"] = float(s["timed_rule_bonus"])
        save_config({
            "speedup": {
                "target_time_initial": CFG["speedup"]["target_time_initial"],
                "target_time_step":    CFG["speedup"]["target_time_step"],
                "target_time_min":     CFG["speedup"]["target_time_min"],
            },
            "lives":   CFG["lives"],
            "audio":   {"volume": CFG["audio"]["volume"]},
            "display": {
                "fullscreen":   CFG["display"]["fullscreen"],
                "fps":          CFG["display"]["fps"],
                "windowed_size": CFG["display"].get("windowed_size", list(WINDOWED_DEFAULT_SIZE)),
            },
            "timed":   {
                "rule_bonus": CFG["timed"]["rule_bonus"],
                "duration":   CFG["timed"].get("duration", TIMED_DURATION),
            },
            "rules": {
                "every_hits": CFG["rules"].get("every_hits", RULE_EVERY_HITS),
                "banner_sec": CFG["rules"].get("banner_sec", RULE_BANNER_SEC),
            },
            "highscore": CFG.get("highscore", 0),
        })
        if self.music_ok:
            pygame.mixer.music.set_volume(float(CFG["audio"]["volume"]))
        self._set_display_mode(bool(CFG["display"]["fullscreen"]))
        self.scene = Scene.MENU

    def settings_cancel(self):
        self.scene = Scene.MENU

    # ----- gameplay flow -----
    def reset_game_state(self):
        self.score = 0
        self.lives = int(self.settings.get("lives", MAX_LIVES))
        self.target = None
        self.target_deadline = None
        self.target_time = float(self.settings.get("target_time_initial", TARGET_TIME_INITIAL))
        self.hits_since_rule = 0
        self.rule = None
        self.rule_banner_until = 0.0
        self.symbol_spawn_time = 0.0
        self.pause_start = 0.0
        self.pause_until = 0.0
        self.time_left = TIMED_DURATION
        self._last_tick = self.now()

    def start_game(self):
        self.scene = Scene.GAME
        self.reset_game_state()
        self._ensure_music()
        if self.mode is Mode.TIMED:
            self._last_tick = self.now()
        if self.music_ok:
            pygame.mixer.music.play(-1)
        self.new_target()

    def end_game(self):
        self.scene = Scene.OVER
        if self.score > self.highscore:
            self.highscore = self.score
            CFG["highscore"] = int(self.highscore)
            save_config({"highscore": CFG["highscore"]})
        if self.music_ok:
            pygame.mixer.music.fadeout(MUSIC_FADEOUT_MS)

    def new_target(self):
        prev = self.target
        choices = [s for s in SYMS if s != prev] if prev else SYMS
        self.target = random.choice(choices)
        self.target_deadline = self.now() + self.target_time if self.mode is Mode.SPEEDUP else None
        self.symbol_spawn_time = self.now()

    def roll_rule(self):
        a = random.choice(SYMS)
        b = random.choice([s for s in SYMS if s != a])
        if self.rule == (a, b):
            b = random.choice([s for s in SYMS if s not in (a, b)])
        self.rule = (a, b)
        now = self.now()
        self.rule_banner_anim_start = now
        self.rule_banner_until = now + RULE_BANNER_TOTAL_SEC
        self.pause_start = now
        self.pause_until = self.rule_banner_until
        if self.mode is Mode.TIMED:
            self.time_left += ADDITIONAL_RULE_TIME

    def apply_rule(self, stimulus: str) -> str:
        return self.rule[1] if (self.rule and stimulus == self.rule[0]) else stimulus

    # ----- input/update -----
    def handle_input_symbol(self, name: str):
        if self.scene is not Scene.GAME or not self.target:
            return
        required = self.apply_rule(self.target)
        if name == required:
            self.score += 1
            self.hits_since_rule += 1
            if self.mode is Mode.TIMED:
                self.time_left += 1.0
            if self.mode is Mode.SPEEDUP:
                step = float(self.settings.get("target_time_step", TARGET_TIME_STEP))
                tmin = float(self.settings.get("target_time_min", TARGET_TIME_MIN))
                self.target_time = max(tmin, self.target_time + step)
            if self.hits_since_rule >= RULE_EVERY_HITS:
                self.hits_since_rule = 0
                self.roll_rule()
            self.new_target()
        else:
            self.trigger_shake()
            self.trigger_glitch()
            if self.mode is Mode.TIMED:
                self.time_left -= 1.0
                if self.time_left <= 0.0:
                    self.time_left = 0.0
                    self.end_game()
            if self.mode is Mode.SPEEDUP:
                self.lives -= 1
                if self.lives <= 0:
                    self.end_game()

    def update(self, iq: InputQueue):
        now = self.now()
        if self.scene is not Scene.GAME:
            return
        if now < self.rule_banner_until and self.rule is not None:
            _ = iq.pop_all()
            self._last_tick = now
            return
        if self.pause_until and now >= self.pause_until:
            paused = max(0.0, self.pause_until - (self.pause_start or self.pause_until))
            self.pause_start = 0.0; self.pause_until = 0.0
            if self.target_deadline is not None:
                self.target_deadline += paused
            self._last_tick = now
        if self.mode is Mode.TIMED:
            dt = max(0.0, now - (self._last_tick or now))
            self.time_left -= dt
            self._last_tick = now
            if self.time_left <= 0.0:
                self.time_left = 0.0
                self.end_game()
                return
        if (self.mode is Mode.SPEEDUP and self.target is not None and
            self.target_deadline is not None and now > self.target_deadline):
            self.lives -= 1
            self.trigger_glitch()
            if self.lives <= 0:
                self.end_game(); return
            self.new_target()
        for n in iq.pop_all():
            self.handle_input_symbol(n)
    
    def handle_event(self, event: pygame.event.Event, iq: InputQueue, keymap: Dict[int, str]):
        if event.type == pygame.VIDEORESIZE:
            self.handle_resize(event.w, event.h)
            return

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_q):
                pygame.quit(); sys.exit(0)

            if self.scene is Scene.MENU:
                if event.key == pygame.K_RETURN:
                    self.start_game()
                elif event.key == pygame.K_m:
                    self.mode = (Mode.TIMED if self.mode is Mode.SPEEDUP else Mode.SPEEDUP)
                elif event.key == pygame.K_o:
                    self.open_settings()

            elif self.scene is Scene.OVER:
                if event.key == pygame.K_SPACE:
                    self.start_game()

            elif self.scene is Scene.SETTINGS:
                if   event.key == pygame.K_ESCAPE:
                    self.settings_cancel()
                elif event.key == pygame.K_RETURN:
                    self.settings_save()
                elif event.key == pygame.K_UP:
                    self.settings_move(-1)
                elif event.key == pygame.K_DOWN:
                    self.settings_move(+1)
                elif event.key == pygame.K_LEFT:
                    self.settings_adjust(-1)
                elif event.key == pygame.K_RIGHT:
                    self.settings_adjust(+1)
                elif event.key == pygame.K_r:
                    self.settings_reset_highscore()

            # mapowanie klawiszy na symbole (działa w każdej scenie)
            name = keymap.get(event.key)
            if name:
                iq.push(name)

    # ----- rendering -----
    def _blit_text(self, font, text, pos, color=INK):
        self.screen.blit(font.render(text, True, color), pos)

    def _draw_timer_bar(self, ratio: float, top_y: int, label: Optional[str] = None):
        ratio = max(0.0, min(1.0, ratio))
        if ratio <= TIMER_BAR_CRIT_TIME:   fill_color = TIMER_BAR_CRIT_COLOR
        elif ratio <= TIMER_BAR_WARN_TIME: fill_color = TIMER_BAR_WARN_COLOR
        else:                              fill_color = TIMER_BAR_FILL
        bar_w = int(self.w * TIMER_BAR_WIDTH_FACTOR)
        bar_h = int(TIMER_BAR_HEIGHT)
        bar_x = (self.w - bar_w) // 2
        bar_y = top_y + self.font.get_height() + TIMER_BAR_MARGIN_TOP
        pygame.draw.rect(self.screen, TIMER_BAR_BG,   (bar_x, bar_y, bar_w, bar_h), border_radius=TIMER_BAR_BORDER_RADIUS)
        fill_w = int(bar_w * ratio)
        pygame.draw.rect(self.screen, fill_color,     (bar_x, bar_y, fill_w, bar_h), border_radius=TIMER_BAR_BORDER_RADIUS)
        pygame.draw.rect(self.screen, TIMER_BAR_BORDER,(bar_x, bar_y, bar_w, bar_h), width=TIMER_BAR_BORDER_W, border_radius=TIMER_BAR_BORDER_RADIUS)
        if label:
            timer_font = getattr(self, "timer_font", self.mid)
            text_surf = timer_font.render(label, True, TIMER_BAR_TEXT_COLOR)
            tx = bar_x + (bar_w - text_surf.get_width()) // 2
            ty = bar_y + (bar_h - text_surf.get_height()) // 2
            shadow = timer_font.render(label, True, (0, 0, 0))
            self.screen.blit(shadow, (tx + 2, ty + 2))
            self.screen.blit(text_surf, (tx, ty))

    def _draw_hud(self):
        top_y = int(self.h * HUD_TOP_MARGIN_FACTOR)
        hud_left = int(self.w * PADDING)
        parts = [f"Score: {self.score}"] if (self.scene is Scene.GAME and self.mode is Mode.TIMED) \
                else [f"Score: {self.score}", f"Lives: {self.lives}"]
        self._blit_text(self.font, HUD_SEPARATOR.join(parts), (hud_left, top_y))
        if self.scene is Scene.GAME:
            if self.mode is Mode.TIMED:
                self._draw_timer_bar(self.time_left / TIMED_DURATION, top_y, f"{self.time_left:.1f}s")
            else:
                if self.target_deadline is not None and self.target_time > 0:
                    remaining = max(0.0, self.target_deadline - self.now())
                    self._draw_timer_bar(remaining / max(0.001, self.target_time), top_y, f"{remaining:.1f}s")
        rule_str = "Rule: none" if not self.rule else f"Rule: {self.rule[0]} → {self.rule[1]}"
        self._blit_text(self.font, rule_str, (hud_left, top_y + self.font.get_height() + 6), color=ACCENT)

    def _ease_out_cubic(self, t: float) -> float:
        t = max(0.0, min(1.0, t)); return 1 - (1 - t) ** 3
    
    def _draw_rule_banner(self):
        now = self.now()
        t = now - self.rule_banner_anim_start
        if t < 0: t = 0
        if t > RULE_BANNER_TOTAL_SEC: t = RULE_BANNER_TOTAL_SEC
        if t <= RULE_BANNER_IN_SEC:      p = self._ease_out_cubic(t / RULE_BANNER_IN_SEC)
        elif t <= RULE_BANNER_IN_SEC + RULE_BANNER_HOLD_SEC: p = 1.0
        else:
            tt = (t - RULE_BANNER_IN_SEC - RULE_BANNER_HOLD_SEC) / max(0.001, RULE_BANNER_OUT_SEC)
            p = 1.0 - self._ease_out_cubic(tt)

        panel_w = int(self.w * RULE_PANEL_W_FACTOR)
        panel_h = int(self.h * RULE_PANEL_H_FACTOR)
        panel_x = (self.w - panel_w) // 2
        mid_y   = int(self.h * 0.30)
        top_y   = -panel_h
        panel_y = int(top_y + (mid_y - top_y) * p)

        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        shadow = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0,0,0,120), shadow.get_rect(), border_radius=RULE_PANEL_RADIUS+2)
        self.screen.blit(shadow, (panel_x+3, panel_y+5))
        pygame.draw.rect(panel, RULE_PANEL_BG, panel.get_rect(), border_radius=RULE_PANEL_RADIUS)
        pygame.draw.rect(panel, RULE_PANEL_BORDER, panel.get_rect(), width=RULE_PANEL_BORDER_W, border_radius=RULE_PANEL_RADIUS)

        icon_size = int(self.w * RULE_ICON_SIZE_FACTOR)
        gap = int(self.w * RULE_ICON_GAP_FACTOR)
        cx = panel_w // 2; cy = panel_h // 2
        left_rect  = pygame.Rect(0, 0, icon_size, icon_size)
        right_rect = pygame.Rect(0, 0, icon_size, icon_size)
        arrow_w = int(icon_size * 1.05); arrow_h = int(icon_size * 0.55)
        arrow_rect = pygame.Rect(0, 0, arrow_w, arrow_h); arrow_rect.center = (cx, cy)
        left_rect.center  = (cx - (arrow_rect.width // 2) - gap - icon_size // 2, cy)
        right_rect.center = (cx + (arrow_rect.width // 2) + gap + icon_size // 2, cy)
        draw_symbol(panel, self.rule[0], left_rect)
        draw_arrow(panel, arrow_rect)
        draw_symbol(panel, self.rule[1], right_rect)
        label = self.mid.render(f"RULE: {self.rule[0]} → {self.rule[1]}", True, ACCENT)
        panel.blit(label, ( (panel_w - label.get_width()) // 2, max(8, cy - icon_size//2 - label.get_height() - 6) ))
        self.screen.blit(panel, (panel_x, panel_y))

    def _draw_spawn_animation(self, surface: pygame.Surface, name: str, rect: pygame.Rect):
        age   = self.now() - self.symbol_spawn_time
        t     = 0.0 if SYMBOL_ANIM_TIME <= 0 else min(1.0, max(0.0, age / SYMBOL_ANIM_TIME))
        eased = 1.0 - (1.0 - t) ** 3  # ease-out-cubic

        base_size = self.w * SYMBOL_BASE_SIZE_FACTOR
        scale     = SYMBOL_ANIM_START_SCALE + (1.0 - SYMBOL_ANIM_START_SCALE) * eased
        size      = base_size * scale

        # zjazd z dołu do środka (efekt głębi)
        start_y = self.h * (0.5 + SYMBOL_ANIM_OFFSET_Y)
        end_y   = self.h * 0.5
        cy      = start_y + (end_y - start_y) * eased

        # shake (delikatny, opcjonalny)
        dx = dy = 0.0
        now = self.now()
        if now < self.shake_until:
            sh_t = (now - self.shake_start) / SHAKE_DURATION
            sh_t = max(0.0, min(1.0, sh_t))
            env = 1.0 - sh_t
            amp = self.w * SHAKE_AMPLITUDE_FACT * env
            phase = 2.0 * math.pi * SHAKE_FREQ_HZ * (now - self.shake_start)
            dx = amp * math.sin(phase)
            dy = 0.5 * amp * math.cos(phase * 0.9)

        draw_rect = pygame.Rect(0, 0, size, size)
        draw_rect.center = (self.w * 0.5 + dx, cy + dy)

        draw_symbol(surface, name, draw_rect)

    def _draw_gameplay(self):
        if self.bg_img: self.screen.blit(self.bg_img, (0, 0))
        else:           self.screen.fill(BG)

        self._draw_hud()

        if self.target:
            base_rect = pygame.Rect(0, 0, self.w * SYMBOL_BASE_SIZE_FACTOR, self.w * SYMBOL_BASE_SIZE_FACTOR)
            base_rect.center = (self.w * 0.5, self.h * 0.5)
            self._draw_spawn_animation(self.screen, self.target, base_rect)

    # --- glitch compositing on framebuffer ---
    def _apply_glitch_effect(self, frame: pygame.Surface) -> pygame.Surface:
        now = self.now()
        if now >= self.glitch_active_until:
            return frame

        dur = max(1e-6, GLITCH_DURATION)
        t = 1.0 - (self.glitch_active_until - now) / dur                # 0..1
        vigor = (1 - abs(0.5 - t) * 2)                                  # najmocniej w środku

        # 1) pixelation
        pf = GLITCH_PIXEL_FACTOR_MAX * vigor
        if pf > 0:
            sw, sh = max(1, int(self.w * (1 - pf))), max(1, int(self.h * (1 - pf)))
            small = pygame.transform.smoothscale(frame, (sw, sh))
            frame = pygame.transform.scale(small, (self.w, self.h))

        out = frame.copy()

        # 2) RGB split
        ch_off = int(6 * vigor) + random.randint(0, 2)
        if ch_off:
            for (mask, dx, dy) in (
                ((255, 0, 0, 255),  ch_off, 0),
                ((0, 255, 0, 255), -ch_off, 0),
                ((0, 0, 255, 255),  0, ch_off),
            ):
                chan = frame.copy()
                tint = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
                tint.fill(mask)
                chan.blit(tint, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
                out.blit(chan, (dx, dy), special_flags=pygame.BLEND_ADD)

        # 3) displaced horizontal bands
        if random.random() < 0.9:
            bands = random.randint(2, 4)
            band_h = max(4, self.h // (bands * 8))
            for _ in range(bands):
                y = random.randint(0, self.h - band_h)
                dx = random.randint(-int(self.w*0.03), int(self.w*0.03))
                slice_rect = pygame.Rect(0, y, self.w, band_h)
                slice_surf = out.subsurface(slice_rect).copy()
                out.blit(slice_surf, (dx, y))

        # 4) colored blocks
        if random.random() < 0.4:
            w = random.randint(self.w // 12, self.w // 4)
            h = random.randint(self.h // 24, self.h // 8)
            x = random.randint(0, max(0, self.w - w))
            y = random.randint(0, max(0, self.h - h))
            col = (random.randint(180, 255), random.randint(120, 255),
                   random.randint(120, 255), random.randint(40, 100))
            pygame.draw.rect(out, col, (x, y, w, h))

        return out

    def trigger_glitch(self):
        now = self.now()
        self.glitch_active_until = now + GLITCH_DURATION
        self.glitch_start_time = now
        self.trigger_shake()

    def draw(self):
        # rysujemy NA BUFOR zamiast bezpośrednio na ekran
        self.fb.fill((0,0,0,0))
        old_screen = self.screen
        self.screen = self.fb  # przekieruj wszystkie metody rysujące
        try:
            if self.scene is Scene.GAME and self.now() < self.rule_banner_until and self.rule:
                if self.bg_img: self.screen.blit(self.bg_img, (0, 0))
                else:           self.screen.fill(BG)
                self._draw_rule_banner()
            elif self.scene is Scene.GAME:
                self._draw_gameplay()
            elif self.scene is Scene.MENU:
                if self.bg_img: self.screen.blit(self.bg_img, (0, 0))
                else:           self.screen.fill(BG)
                # menu
                title = self.big.render("4-Symbols", True, INK)
                self.screen.blit(title, (self.w/2 - title.get_width()/2, self.h*MENU_TITLE_Y_FACTOR))
                mode_label = "SPEED-UP" if self.mode is Mode.SPEEDUP else "TIMED"
                mode_text = self.mid.render(f"Mode: {mode_label}  (M = change)", True, ACCENT)
                self.screen.blit(mode_text, (self.w/2 - mode_text.get_width()/2,
                                             self.h*MENU_TITLE_Y_FACTOR + title.get_height() + MENU_MODE_GAP))
                hint = self.font.render("ENTER = start   ·   ESC/Q = quit", True, INK)
                self.screen.blit(hint, (self.w/2 - hint.get_width()/2,
                                        self.h*MENU_TITLE_Y_FACTOR + title.get_height() + MENU_HINT_GAP + mode_text.get_height()))
                hint2 = self.font.render("O = settings", True, INK)
                self.screen.blit(hint2, (self.w/2 - hint2.get_width()/2,
                                         self.h*MENU_TITLE_Y_FACTOR + title.get_height() + MENU_HINT_GAP + mode_text.get_height() + hint.get_height() + MENU_HINT2_EXTRA_GAP))
            elif self.scene is Scene.OVER:
                if self.bg_img: self.screen.blit(self.bg_img, (0, 0))
                else:           self.screen.fill(BG)
                over = self.big.render("GAME OVER", True, INK)
                self.screen.blit(over, (self.w/2 - over.get_width()/2, self.h/2 - over.get_height()/2 + OVER_TITLE_OFFSET_Y))
                score_s = self.mid.render(f"Score: {self.score}", True, ACCENT)
                hs_s    = self.mid.render(f"Best:  {self.highscore}", True, ACCENT)
                self.screen.blit(score_s, (self.w/2 - score_s.get_width()/2, self.h/2 - score_s.get_height()/2 + OVER_SCORE_GAP1))
                self.screen.blit(hs_s,    (self.w/2 - hs_s.get_width()/2,    self.h/2 - hs_s.get_height()/2 + OVER_SCORE_GAP2))
                info = self.font.render("SPACE = play again   ·   ESC = quit", True, INK)
                self.screen.blit(info, (self.w/2 - info.get_width()/2, self.h/2 + OVER_INFO_GAP))
            elif self.scene is Scene.SETTINGS:
                if self.bg_img: self.screen.blit(self.bg_img, (0, 0))
                else:           self.screen.fill(BG)
                title = self.big.render("Settings", True, INK)
                self.screen.blit(title, (self.w/2 - title.get_width()/2, self.h*SETTINGS_TITLE_Y_FACTOR))
                items = self.settings_items()
                y = self.h * SETTINGS_LIST_Y_START_FACTOR
                for i, (label, value, key) in enumerate(items):
                    is_sel = (i == self.settings_idx and key is not None)
                    surf = self.mid.render(f"{label}: {value}", True, ACCENT if is_sel else INK)
                    self.screen.blit(surf, (self.w/2 - surf.get_width()/2, y))
                    y += surf.get_height() + SETTINGS_ITEM_SPACING
                help1 = self.font.render("↑/↓ select · ←/→ adjust · R reset high score", True, INK)
                help2 = self.font.render("ENTER save · ESC back", True, INK)
                self.screen.blit(help1, (self.w/2 - help1.get_width()/2, y + SETTINGS_HELP_MARGIN_TOP))
                self.screen.blit(help2, (self.w/2 - help2.get_width()/2, y + SETTINGS_HELP_MARGIN_TOP + help1.get_height() + SETTINGS_HELP_GAP))
        finally:
            # przywróć
            self.screen = old_screen

        # nałóż glitch na bufor, a potem wyświetl
        final_surface = self._apply_glitch_effect(self.fb)
        self.screen.blit(final_surface, (0, 0))
        pygame.display.flip()

# ========= MAIN LOOP =========
def main():
    os.environ['SDL_VIDEO_WINDOW_POS'] = "0,0"  # start w lewym górnym rogu

    pygame.init()
    fullscreen = bool(CFG.get("display", {}).get("fullscreen", True))
    screen = pygame.display.set_mode((1, 1))
    game = Game(screen, mode=Mode.SPEEDUP)
    game._set_display_mode(fullscreen)
    pygame.display.set_caption("4-Symbols")

    iq = InputQueue()
    _ = init_gpio(iq)

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit(0)
            game.handle_event(event, iq, KEYMAP)

        game.update(iq)
        game.draw()
        game.clock.tick(FPS)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pygame.quit(); sys.exit(0)
