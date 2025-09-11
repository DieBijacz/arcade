from __future__ import annotations
import json, os, random, sys, time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, Optional, Tuple
import pygame

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
    s["target_time_initial"] = float(max(0.2, min(10.0, s["target_time_initial"])))
    s["target_time_min"]     = float(max(0.1, min(s["target_time_initial"], s["target_time_min"])))
    s["target_time_step"]    = float(max(-1.0, min(1.0, s["target_time_step"])))
    cfg["lives"]             = int(max(1, min(9, cfg["lives"])))
    cfg["audio"]["volume"]   = float(max(0.0, min(1.0, cfg["audio"]["volume"])))
    if "fps" in cfg["display"]:
        cfg["display"]["fps"] = int(max(30, min(240, cfg["display"]["fps"])))
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

def init_gpio(iq: InputQueue):
    if IS_WINDOWS or not GPIO_AVAILABLE:
        return {}
    pins = {"CIRCLE": PINS.CIRCLE, "CROSS": PINS.CROSS, "SQUARE": PINS.SQUARE, "TRIANGLE": PINS.TRIANGLE}
    buttons = {name: Button(pin, pull_up=True, bounce_time=0.05) for name, pin in pins.items()}
    for name, btn in buttons.items():
        btn.when_pressed = (lambda n=name: iq.push(n))
    return buttons

# ========= CONSTANTS (visuals & gameplay) =========
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

FPS                   = CFG["display"]["fps"]
TARGET_TIME_INITIAL   = CFG["speedup"]["target_time_initial"]
TARGET_TIME_MIN       = CFG["speedup"]["target_time_min"]
TARGET_TIME_STEP      = CFG["speedup"]["target_time_step"]
TIMED_DURATION        = CFG["timed"]["duration"]
RULE_EVERY_HITS       = CFG["rules"]["every_hits"]
RULE_BANNER_SEC       = CFG["rules"]["banner_sec"]
MAX_LIVES             = CFG["lives"]
ADDITIONAL_RULE_TIME  = float(CFG["timed"].get("rule_bonus", 5.0))

# Animacja i rozmiary symbolu
SYMBOL_BASE_SIZE_FACTOR  = 0.26   # ← główny rozmiar symbolu względem szerokości okna
SYMBOL_ANIM_TIME         = 0.30
SYMBOL_ANIM_START_SCALE  = 0.20
SYMBOL_ANIM_OFFSET_Y     = 0.08

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
        thickness = 20
        cx, cy = rect.center
        w, h = rect.size
        r = min(w, h) * 0.32
        if name == "CIRCLE":
            pygame.draw.circle(surface, color, (int(cx), int(cy)), int(r), thickness)
        elif name == "SQUARE":
            side = r * 1.6
            rr = pygame.Rect(0, 0, side, side); rr.center = rect.center
            pygame.draw.rect(surface, color, rr, thickness, border_radius=8)
        elif name == "TRIANGLE":
            a = (cx, cy - r); b = (cx - r * 0.9, cy + r * 0.9); c = (cx + r * 0.9, cy + r * 0.9)
            pygame.draw.polygon(surface, color, [a, b, c], thickness)
        elif name == "CROSS":
            k = r * 1
            pygame.draw.line(surface, color, (cx - k, cy - k), (cx + k, cy + k), thickness)
            pygame.draw.line(surface, color, (cx - k, cy + k), (cx + k, cy - k), thickness)
    else:
        img_w, img_h = img.get_size()
        scale = min(rect.width / img_w, rect.height / img_h)
        new_size = (int(img_w * scale), int(img_h * scale))
        scaled_img = pygame.transform.smoothscale(img, new_size)
        img_rect = scaled_img.get_rect(center=rect.center)
        surface.blit(scaled_img, img_rect)

# ========= GAME =========
class Game:
    def __init__(self, screen: pygame.Surface, mode: Mode = Mode.SPEEDUP):
        self.screen = screen
        self.mode: Mode = mode
        self.scene: Scene = Scene.MENU

        self.w, self.h = self.screen.get_size()
        self.clock = pygame.time.Clock()
        font_path = "assets/font/Orbitron-VariableFont_wght.ttf"
        self.font = pygame.font.Font(font_path, 24)
        self.big  = pygame.font.Font(font_path, 48)
        self.mid  = pygame.font.Font(font_path, 36)

        self.bg_img_raw = self._load_background()
        self.bg_img = None

        self._recompute_layout()
        self._rescale_background()

        # gameplay state
        self.score = 0
        self.lives = MAX_LIVES
        self.target: Optional[str] = None
        self.target_deadline: Optional[float] = None
        self.target_time = TARGET_TIME_INITIAL
        self.flash: Optional[tuple[str, float, Tuple[int,int,int]]] = None
        self.hits_since_rule = 0
        self.rule: Optional[Tuple[str,str]] = None
        self.rule_banner_until = 0.0
        self.pause_start = 0.0
        self.pause_until = 0.0
        self.symbol_spawn_time = 0.0
        self.time_left = TIMED_DURATION
        self._last_tick = 0.0
        self.highscore = int(CFG.get("highscore", 0))

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

    # ----- utils -----
    def now(self) -> float: return time.time()

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

    def _load_background(self):
        path = CFG.get("images", {}).get("background") if isinstance(CFG.get("images"), dict) else None
        if not path or not os.path.exists(path):
            return None
        return IMAGES.load(path, allow_alpha=True)

    def _rescale_background(self):
        raw = getattr(self, "bg_img_raw", None)
        self.bg_img = pygame.transform.smoothscale(raw, (self.w, self.h)) if raw else None

    def _set_display_mode(self, fullscreen: bool):
        if fullscreen:
            flags, size = pygame.FULLSCREEN, (0, 0)
        else:
            size = tuple(CFG.get("display", {}).get("windowed_size", (720, 1280)))
            flags = 0
        self.screen = pygame.display.set_mode(size, flags)
        self._recompute_layout()

    # ----- settings (model + UI list) -----
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
        s["target_time_min"]     = max(0.1, min(float(s["target_time_initial"]), float(s["target_time_min"])))
        s["target_time_step"]    = max(-1.0, min(1.0, float(s["target_time_step"])))
        s["lives"]               = max(1, min(9, int(s["lives"])))
        s["volume"]              = max(0.0, min(1.0, float(s["volume"])))
        s["timed_rule_bonus"]    = max(0.0, min(30.0, float(s["timed_rule_bonus"])))

    def apply_fullscreen_now(self):
        want_full = bool(self.settings.get("fullscreen", True))
        flags = pygame.FULLSCREEN if want_full else 0
        self.screen = pygame.display.set_mode((0,0) if want_full else (720,1280), flags)
        self._recompute_layout()

    def settings_adjust(self, delta: int):
        items = self.settings_items()
        key = items[self.settings_idx][2]
        if key is None:
            return
        if key == "fullscreen":
            self.settings["fullscreen"] = not self.settings["fullscreen"]
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
        })
        self.settings_idx = 0
        self.settings_move(0)
        self.scene = Scene.SETTINGS()

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
        save_config({
            "speedup": {
                "target_time_initial": CFG["speedup"]["target_time_initial"],
                "target_time_step":    CFG["speedup"]["target_time_step"],
                "target_time_min":     CFG["speedup"]["target_time_min"],
            },
            "lives":   CFG["lives"],
            "audio":   {"volume": CFG["audio"]["volume"]},
            "display": {"fullscreen": CFG["display"]["fullscreen"]},
            "timed":   {"rule_bonus": CFG["timed"]["rule_bonus"]},
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
        self.flash = None
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
            pygame.mixer.music.fadeout(800)

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
        self.rule_banner_until = now + RULE_BANNER_SEC
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
            self.flash = (name, self.now() + 0.18, PAD_GOOD)
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
            if self.mode is Mode.TIMED:
                self.time_left -= 1.0
                self.flash = (name, self.now() + 0.18, PAD_BAD)
                self.new_target()
                if self.time_left <= 0.0:
                    self.time_left = 0.0
                    self.end_game()
                return
            self.lives -= 1
            self.flash = (name, self.now() + 0.18, PAD_BAD)
            if self.lives <= 0:
                self.end_game()
            else:
                self.new_target()

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
            self.pause_start = 0.0
            self.pause_until = 0.0
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
            self.flash = (self.apply_rule(self.target), now + 0.18, PAD_BAD)
            if self.lives <= 0:
                self.end_game(); return
            self.new_target()
        for n in iq.pop_all():
            self.handle_input_symbol(n)

    # ----- event routing -----
    def handle_event(self, event: pygame.event.Event, iq: InputQueue, keymap: Dict[int, str]):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_q):
                pygame.quit(); sys.exit(0)
            if self.scene is Scene.MENU:
                if event.key == pygame.K_RETURN: self.start_game()
                elif event.key == pygame.K_m:    self.mode = (Mode.TIMED if self.mode is Mode.SPEEDUP else Mode.SPEEDUP)
                elif event.key == pygame.K_o:    self.open_settings()
            elif self.scene is Scene.OVER:
                if event.key == pygame.K_SPACE:  self.start_game()
            elif self.scene is Scene.SETTINGS:
                if   event.key == pygame.K_ESCAPE: self.settings_cancel()
                elif event.key == pygame.K_RETURN: self.settings_save()
                elif event.key == pygame.K_UP:     self.settings_move(-1)
                elif event.key == pygame.K_DOWN:   self.settings_move(+1)
                elif event.key == pygame.K_LEFT:   self.settings_adjust(-1)
                elif event.key == pygame.K_RIGHT:  self.settings_adjust(+1)
                elif event.key == pygame.K_r:      self.settings_reset_highscore()
            name = keymap.get(event.key)
            if name:
                iq.push(name)

    # ----- rendering -----
    def _blit_text(self, font, text, pos, color=INK):
        self.screen.blit(font.render(text, True, color), pos)

    def _draw_hud(self):
        top_y = int(self.h * 0.02)
        hud_left = int(self.w * PADDING)
        parts = [f"Score: {self.score}"] if (self.scene is Scene.GAME and self.mode is Mode.TIMED) \
                else [f"Score: {self.score}", f"Lives: {self.lives}"]
        self._blit_text(self.font, "   ·   ".join(parts), (hud_left, top_y))

        if self.scene is Scene.GAME and self.mode is Mode.TIMED:
            bar_w = int(self.w * 0.6); bar_h = 18
            bar_x = (self.w - bar_w) // 2; bar_y = top_y + self.font.get_height() + 10
            pygame.draw.rect(self.screen, (40, 40, 50), (bar_x, bar_y, bar_w, bar_h), border_radius=8)
            ratio = max(0.0, min(1.0, self.time_left / TIMED_DURATION))
            fill_w = int(bar_w * ratio)
            pygame.draw.rect(self.screen, (90, 200, 255), (bar_x, bar_y, fill_w, bar_h), border_radius=8)
            pygame.draw.rect(self.screen, (160, 180, 200), (bar_x, bar_y, bar_w, bar_h), width=2, border_radius=8)

        rule_str = "Rule: none" if not self.rule else f"Rule: {self.rule[0]} → {self.rule[1]}"
        self._blit_text(self.font, rule_str, (hud_left, top_y + self.font.get_height() + 6), color=ACCENT)

    def _draw_rule_banner(self):
        size = self.w * 0.22
        left  = pygame.Rect(0, 0, size, size)
        right = pygame.Rect(0, 0, size, size)
        gap = self.w * 0.06
        left.center  = (self.w/2 - (size/2 + gap/2), self.h/2)
        right.center = (self.w/2 + (size/2 + gap/2), self.h/2)
        draw_symbol(self.screen, self.rule[0], left)
        draw_symbol(self.screen, self.rule[1], right)
        arrow = self.big.render("→", True, INK)
        self.screen.blit(arrow, (self.w/2 - arrow.get_width()/2, self.h/2 - arrow.get_height()/2))
        rule_text = self.mid.render(f"Rule: {self.rule[0]} → {self.rule[1]}", True, ACCENT)
        text_rect = rule_text.get_rect(center=(self.w/2, self.h/2 - size/2 - self.mid.get_height()))
        self.screen.blit(rule_text, text_rect)

    def _draw_gameplay(self):
        if self.bg_img: self.screen.blit(self.bg_img, (0, 0))
        else:           self.screen.fill(BG)
        self._draw_hud()

        if self.target:
            # easing: fast start, slow end
            age = self.now() - self.symbol_spawn_time
            t = 0.0 if SYMBOL_ANIM_TIME <= 0 else min(1.0, max(0.0, age / SYMBOL_ANIM_TIME))
            eased = 1.0 - (1.0 - t) ** 3

            base_size = self.w * SYMBOL_BASE_SIZE_FACTOR
            scale     = SYMBOL_ANIM_START_SCALE + (1.0 - SYMBOL_ANIM_START_SCALE) * eased
            size      = base_size * scale

            start_y = self.h * (0.5 + SYMBOL_ANIM_OFFSET_Y)
            end_y   = self.h * 0.5
            cy      = start_y + (end_y - start_y) * eased

            center_rect = pygame.Rect(0, 0, size, size)
            center_rect.center = (self.w * 0.5, cy)
            draw_symbol(self.screen, self.target, center_rect)

        if self.flash and time.time() < self.flash[1]:
            pygame.draw.rect(self.screen, self.flash[2], self.screen.get_rect(), width=10, border_radius=12)

    def _draw_menu(self):
        title = self.big.render("4-Symbols", True, INK)
        self.screen.blit(title, (self.w/2 - title.get_width()/2, self.h*0.28))
        mode_label = "SPEED-UP" if self.mode is Mode.SPEEDUP else "TIMED"
        mode_text = self.mid.render(f"Mode: {mode_label}  (M = change)", True, ACCENT)
        self.screen.blit(mode_text, (self.w/2 - mode_text.get_width()/2, self.h*0.28 + title.get_height() + 20))
        hint = self.font.render("ENTER = start   ·   ESC/Q = quit", True, INK)
        self.screen.blit(hint, (self.w/2 - hint.get_width()/2, self.h*0.28 + title.get_height() + mode_text.get_height() + 48))
        hint2 = self.font.render("O = settings", True, INK)
        self.screen.blit(hint2, (self.w/2 - hint2.get_width()/2, self.h*0.28 + title.get_height() + mode_text.get_height() + 48 + hint.get_height() + 12))

    def _draw_over(self):
        over = self.big.render("GAME OVER", True, INK)
        self.screen.blit(over, (self.w/2 - over.get_width()/2, self.h/2 - over.get_height()/2 - 60))
        score_s = self.mid.render(f"Score: {self.score}", True, ACCENT)
        hs_s    = self.mid.render(f"Best:  {self.highscore}", True, ACCENT)
        self.screen.blit(score_s, (self.w/2 - score_s.get_width()/2, self.h/2 - score_s.get_height()/2 - 10))
        self.screen.blit(hs_s,    (self.w/2 - hs_s.get_width()/2,    self.h/2 - hs_s.get_height()/2 + 26))
        info = self.font.render("SPACE = play again   ·   ESC = quit", True, INK)
        self.screen.blit(info, (self.w/2 - info.get_width()/2, self.h/2 + 60))

    def _draw_settings(self):
        title = self.big.render("Settings", True, INK)
        self.screen.blit(title, (self.w/2 - title.get_width()/2, self.h*0.18))
        items = self.settings_items()
        y = self.h * 0.26
        for i, (label, value, key) in enumerate(items):
            is_sel = (i == self.settings_idx and key is not None)
            surf = self.mid.render(f"{label}: {value}", True, ACCENT if is_sel else INK)
            self.screen.blit(surf, (self.w/2 - surf.get_width()/2, y))
            y += surf.get_height() + 14
        help1 = self.font.render("↑/↓ select · ←/→ adjust · R reset high score", True, INK)
        help2 = self.font.render("ENTER save · ESC back", True, INK)
        self.screen.blit(help1, (self.w/2 - help1.get_width()/2, y + 18))
        self.screen.blit(help2, (self.w/2 - help2.get_width()/2, y + 18 + help1.get_height() + 6))

    def draw(self):
        if self.scene is Scene.GAME and self.now() < self.rule_banner_until and self.rule:
            if self.bg_img: self.screen.blit(self.bg_img, (0, 0))
            else:           self.screen.fill(BG)
            self._draw_rule_banner()
        elif self.scene is Scene.GAME:
            self._draw_gameplay()
        elif self.scene is Scene.MENU:
            if self.bg_img: self.screen.blit(self.bg_img, (0, 0))
            else:           self.screen.fill(BG)
            self._draw_menu()
        elif self.scene is Scene.OVER:
            if self.bg_img: self.screen.blit(self.bg_img, (0, 0))
            else:           self.screen.fill(BG)
            self._draw_over()
        elif self.scene is Scene.SETTINGS:
            if self.bg_img: self.screen.blit(self.bg_img, (0, 0))
            else:           self.screen.fill(BG)
            self._draw_settings()
        pygame.display.flip()

# ========= MAIN LOOP =========
def main():
    pygame.init()
    fullscreen = bool(CFG.get("display", {}).get("fullscreen", True))
    screen = pygame.display.set_mode((1, 1))
    game = Game(screen, mode=Mode.SPEEDUP)
    game._set_display_mode(fullscreen)
    pygame.display.set_caption("4-Symbols")

    iq = InputQueue()
    _ = init_gpio(iq)

    keymap: Dict[int, str] = {
        pygame.K_UP: "TRIANGLE", pygame.K_RIGHT: "CIRCLE",  pygame.K_LEFT: "SQUARE", pygame.K_DOWN: "CROSS",
        pygame.K_w:  "TRIANGLE", pygame.K_d:     "CIRCLE",  pygame.K_a:   "SQUARE", pygame.K_s:   "CROSS",
    }

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit(0)
            game.handle_event(event, iq, keymap)

        game.update(iq)
        game.draw()
        game.clock.tick(CFG["display"]["fps"])

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pygame.quit(); sys.exit(0)
