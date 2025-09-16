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
    "rules":      {"every_hits": 10, "banner_sec": 2.0, "banner_font_center": 64, "banner_font_pinned": 40 },
    "lives":      3,
    "audio":      {"music": "assets/music.ogg", "volume": 0.5},
    "effects":   { "glitch_enabled": True },
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
    r = cfg.setdefault("rules", {})
    r["banner_font_center"] = int(max(8, min(200, r.get("banner_font_center", 64))))
    r["banner_font_pinned"] = int(max(8, min(200, r.get("banner_font_pinned", 40))))
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
BG       = (8, 10, 12)         # kolor tła sceny
PAD      = (40, 44, 52)        # bazowy kolor padów/paneli
PAD_HI   = (90, 200, 255)      # kolor podświetlenia aktywnego elementu
PAD_GOOD = (60, 200, 120)      # kolor akcji poprawnej
PAD_BAD  = (220, 80, 80)       # kolor akcji błędnej
INK      = (235, 235, 235)     # podstawowy kolor tekstu/ikon
ACCENT   = (255, 210, 90)      # akcent (ważne etykiety, wyróżnienia)

SYMBOL_COLORS = {
    "TRIANGLE": (0, 255, 0),    # kolor rysowanego trójkąta (fallback, gdy brak obrazka)
    "CIRCLE":   (255, 0, 0),    # kolor rysowanego koła
    "CROSS":    (0, 0, 255),    # kolor rysowanego krzyżyka
    "SQUARE":   (255, 215, 0),  # kolor rysowanego kwadratu
}

PADDING = 0.06                 # marginesy sceny względem szer./wys. ekranu
GAP     = 0.04                 # przerwa między „padami”/panelami
FPS     = CFG["display"]["fps"]  # docelowa liczba klatek

TARGET_TIME_INITIAL   = CFG["speedup"]["target_time_initial"]  # początkowy limit czasu na trafienie (Speed-Up)
TARGET_TIME_MIN       = CFG["speedup"]["target_time_min"]      # minimalny limit czasu (nie schodzi niżej)
TARGET_TIME_STEP      = CFG["speedup"]["target_time_step"]     # zmiana limitu czasu po każdej poprawnej akcji
TIMED_DURATION        = CFG["timed"]["duration"]               # łączny czas w trybie Timed
RULE_EVERY_HITS       = CFG["rules"]["every_hits"]             # co ile trafień losujemy nową zasadę
RULE_BANNER_SEC       = CFG["rules"]["banner_sec"]             # łączny czas wyświetlenia baneru reguły (legacy)
MAX_LIVES             = CFG["lives"]                           # maksymalna liczba żyć (tryb Speed-Up)
ADDITIONAL_RULE_TIME  = float(CFG["timed"].get("rule_bonus", 5.0))  # bonus czasu po wylosowaniu reguły (Timed)

SYMBOL_BASE_SIZE_FACTOR  = 0.26  # bazowa wielkość symbolu względem szerokości ekranu
SYMBOL_ANIM_TIME         = 0.30  # czas animacji pojawiania się symbolu
SYMBOL_ANIM_START_SCALE  = 0.20  # startowa skala symbolu w animacji
SYMBOL_ANIM_OFFSET_Y     = 0.08  # początkowe przesunięcie Y (względem wysokości ekranu)

SHAKE_DURATION        = 0.12  # czas trzęsienia ekranu po błędzie
SHAKE_AMPLITUDE_FACT  = 0.012 # amplituda trzęsienia (względem szerokości ekranu)
SHAKE_FREQ_HZ         = 18.0  # częstotliwość wibracji

UI_RADIUS = 8  # promień zaokrągleń elementów UI

SYMBOL_DRAW_THICKNESS         = 20   # grubość linii przy rysowaniu symboli wektorowych
SYMBOL_SQUARE_RADIUS          = UI_RADIUS  # zaokrąglenie rogów kwadratu
SYMBOL_CIRCLE_RADIUS_FACTOR   = 0.32  # promień koła względem mniejszego boku prostokąta
SYMBOL_TRIANGLE_POINT_FACTOR  = 0.9   # „ostrość” wierzchołków trójkąta
SYMBOL_CROSS_K_FACTOR         = 1.0   # długość ramion krzyżyka względem promienia

HUD_TOP_MARGIN_FACTOR = 0.02  # górny margines HUD (od ekranu)
HUD_SEPARATOR         = "   ·   "  # separator tekstowy w HUD

# --- Glitch ---
GLITCH_DURATION = 0.20           # czas trwania efektu glitch
GLITCH_PIXEL_FACTOR_MAX = 0.10   # maks. pikselizacja (skala)
GLITCH_FREQ_HZ = 60.0            # częstotliwość zmian/glitcha

# --- Text Glitch ---
TEXT_GLITCH_DURATION   = 0.5     # czas trwania „zepsutego” tekstu
TEXT_GLITCH_MIN_GAP    = 1       # minimalna przerwa między glitchami tekstu
TEXT_GLITCH_MAX_GAP    = 5.0     # maksymalna przerwa między glitchami tekstu
TEXT_GLITCH_CHAR_PROB  = 0.01    # prawdopodobieństwo podmiany znaku
TEXT_GLITCH_CHARSET    = "01+-_#@$%&*[]{}<>/\\|≈≠∆░▒▓"  # zestaw znaków do podmiany

# --- Spawn anim ---
SYMBOL_SPAWN_ANIM_DURATION = 0.40    # czas „spawnu” symbolu
SYMBOL_SPAWN_GLITCH_DURATION = 0.02  # króciutki glitch przy spawnie
SYMBOL_SPAWN_GLOW_MAX_ALPHA = 20     # maks. alfa poświaty przy spawnie
SYMBOL_SPAWN_GLOW_RADIUS_FACTOR = 1.15  # promień poświaty względem symbolu

# --- Timer bar (na dole) ---
TIMER_BAR_WIDTH_FACTOR = 0.60     # szerokość paska czasu względem szerokości ekranu
TIMER_BAR_HEIGHT       = 18       # wysokość paska
TIMER_BAR_MARGIN_TOP   = 10       # wewn. margines górny paska (dla warstw)
TIMER_BAR_BG           = (40, 40, 50)   # kolor tła paska
TIMER_BAR_FILL         = (90, 200, 255) # kolor wypełnienia paska
TIMER_BAR_BORDER       = (160, 180, 200) # kolor obramowania
TIMER_BAR_BORDER_W     = 2        # grubość obramowania
TIMER_BAR_WARN_COLOR   = (255, 170, 80) # kolor stanu ostrzegawczego
TIMER_BAR_CRIT_COLOR   = (220, 80, 80)  # kolor stanu krytycznego
TIMER_BAR_WARN_TIME    = 0.33     # próg (ułamek 0..1) dla ostrzeżenia
TIMER_BAR_CRIT_TIME    = 0.15     # próg (ułamek 0..1) dla krytyku
TIMER_BAR_BORDER_RADIUS= UI_RADIUS  # zaokrąglenie paska
TIMER_BOTTOM_MARGIN_FACTOR = 0.03   # margines od dołu ekranu
TIMER_BAR_TEXT_COLOR   = INK       # kolor etykiety czasu
TIMER_FONT_SIZE        = 48        # rozmiar czcionki etykiety czasu
TIMER_POSITION_INDICATOR_W   = 4   # szerokość pionowego wskaźnika pozycji
TIMER_POSITION_INDICATOR_PAD = 3   # margines wskaźnika względem paska
TIMER_LABEL_GAP              = 8   # odstęp etykiety od paska

# --- Rule banner ---
RULE_BANNER_IN_SEC      = 0.35       # czas wjazdu banera
RULE_BANNER_HOLD_SEC    = 2.0       # czas pozostania na środku
RULE_BANNER_TO_TOP_SEC  = 0.35       # czas wyjazdu do góry/doku
RULE_BANNER_TOTAL_SEC   = RULE_BANNER_IN_SEC + RULE_BANNER_HOLD_SEC + RULE_BANNER_TO_TOP_SEC  # łączny czas animacji
RULE_PANEL_W_FACTOR     = 0.75       # szerokość panelu względem ekranu
RULE_PANEL_H_FACTOR     = 0.30       # wysokość panelu względem ekranu
RULE_PANEL_BG           = (22, 26, 34, 110)  # kolor tła panelu (z alfa)
RULE_PANEL_BORDER       = (120, 200, 255)    # kolor ramki panelu
RULE_PANEL_BORDER_W     = 3          # grubość ramki panelu
RULE_PANEL_RADIUS       = 30         # zaokrąglenie rogów panelu
RULE_ICON_SIZE_FACTOR   = 0.1        # wielkość ikon (w panelu) względem szerokości ekranu
RULE_BANNER_LABEL_GAP   = 2          # odstęp między etykietą a ikonami
RULE_ICON_GAP_FACTOR    = 0.04       # odstęp między ikonami a strzałką w panelu
RULE_ARROW_W            = 6          # grubość rysowanej strzałki
RULE_ARROW_COLOR        = (200, 220, 255)  # kolor strzałki

# Skale panelu i symboli
RULE_BANNER_PIN_SCALE       = 0.60  # skala panelu gdy „zadokowany” pod HUD
RULE_SYMBOL_SCALE_CENTER    = 1.00  # skala symboli w fazie środkowej animacji
RULE_SYMBOL_SCALE_PINNED    = 0.70  # skala symboli w wersji zadokowanej
RULE_SYMBOL_Y_OFFSET_CENTER = 0.00  # pionowe przesunięcie ikon w fazie środkowej
RULE_SYMBOL_Y_OFFSET_PINNED = 0.1   # pionowe przesunięcie ikon w doku

# --- Screens ---
MENU_TITLE_Y_FACTOR   = 0.28  # pionowa pozycja tytułu w menu
MENU_MODE_GAP         = 20    # odstęp pod tytułem dla „Mode”
MENU_HINT_GAP         = 48    # odstęp do linii z podpowiedziami
MENU_HINT2_EXTRA_GAP  = 12    # dodatkowy odstęp dla drugiej podpowiedzi
OVER_TITLE_OFFSET_Y   = -60   # przesunięcie „GAME OVER” w pionie
OVER_SCORE_GAP1       = -10   # odstęp dla napisu „Score”
OVER_SCORE_GAP2       = 26    # odstęp dla napisu „Best”
OVER_INFO_GAP         = 60    # odstęp dla info o sterowaniu
SETTINGS_TITLE_Y_FACTOR       = 0.18 # pozycja tytułu Settings
SETTINGS_LIST_Y_START_FACTOR  = 0.26 # start listy opcji w Settings
SETTINGS_ITEM_SPACING         = 14   # pionowy odstęp między pozycjami
SETTINGS_HELP_MARGIN_TOP      = 18   # margines nad helpem
SETTINGS_HELP_GAP             = 6    # odstęp między liniami helpa

# --- Aspect ---
ASPECT_RATIO            = (9, 16)  # docelowe proporcje okna
ASPECT_SNAP_MIN_SIZE    = (360, 640)  # minimalny rozmiar przy „snappowaniu”
ASPECT_SNAP_TOLERANCE   = 0.0     # tolerancja uznania, że proporcje już są OK

# --- Fonts ---
FONT_PATH        = "assets/font/Orbitron-VariableFont_wght.ttf"  # ścieżka do fontu
FONT_SIZE_SMALL  = 24   # mała czcionka UI
FONT_SIZE_MID    = 48   # średnia czcionka (np. Score w HUD)
FONT_SIZE_BIG    = 80   # duża czcionka (tytuły)

# --- Audio ---
MUSIC_FADEOUT_MS = 800  # czas wyciszania muzyki przy końcu gry (ms)

# --- Window ---
WINDOWED_DEFAULT_SIZE = tuple(CFG.get("display", {}).get("windowed_size", (720, 1280)))  # domyślny rozmiar okna
WINDOWED_FLAGS        = pygame.RESIZABLE  # flagi trybu okienkowego

# --- GPIO ---
GPIO_PULL_UP      = True  # konfiguracja wejść: pull-up
GPIO_BOUNCE_TIME  = 0.05  # czas antydrgań przycisków (s)

# --- Keymap ---
KEYMAP: Dict[int, str] = {
    pygame.K_UP: "TRIANGLE",  # mapowanie klawiszy na symbole (strzałki)
    pygame.K_RIGHT: "CIRCLE",
    pygame.K_LEFT: "SQUARE",
    pygame.K_DOWN: "CROSS",
    pygame.K_w:  "TRIANGLE",  # mapowanie alternatywne (WASD)
    pygame.K_d:  "CIRCLE",
    pygame.K_a:  "SQUARE",
    pygame.K_s:  "CROSS",
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

# ========= GAME =========
class Game:
    def __init__(self, screen: pygame.Surface, mode: Mode = Mode.SPEEDUP):
        self.screen = screen
        self.cfg = CFG
        self.images = IMAGES
        self.mode: Mode = mode
        self.scene: Scene = Scene.MENU

        self.w, self.h = self.screen.get_size()
        self.clock = pygame.time.Clock()

        # key delay
        self.keys_down = set()         
        self.lock_until_all_released = False  
        self.accept_after = 0.0        

        self.font       = pygame.font.Font(FONT_PATH, FONT_SIZE_SMALL)
        self.big        = pygame.font.Font(FONT_PATH, FONT_SIZE_BIG)
        self.mid        = pygame.font.Font(FONT_PATH, FONT_SIZE_MID)
        self.timer_font = pygame.font.Font(FONT_PATH, TIMER_FONT_SIZE)
        self.rule_font_center = None  
        self.rule_font_pinned = None  
        self._build_rule_fonts()

        self.bg_img_raw = self._load_background()
        self.bg_img = None

        self._recompute_layout()
        self._rescale_background()

        # offscreen framebuffer
        self.fb = pygame.Surface((self.w, self.h), pygame.SRCALPHA)

        # gameplay state
        self.score = 0
        self.lives = MAX_LIVES
        self.streak = 0
        self.target: Optional[str] = None
        self.target_deadline: Optional[float] = None
        self.target_time = TARGET_TIME_INITIAL
        self.hits_since_rule = 0
        self.rule: Optional[Tuple[str,str]] = None
        self.rule_banner_from_pinned = False
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
        self.glitch_mag = 1.0
        self.text_glitch_active_until = 0.0
        self.next_text_glitch_at = self.now() + random.uniform(TEXT_GLITCH_MIN_GAP, TEXT_GLITCH_MAX_GAP)

        # settings buffer (ekran Settings)
        self.settings_idx = 0
        self.settings = {
            "target_time_initial": float(CFG["speedup"]["target_time_initial"]),
            "target_time_step":    float(CFG["speedup"]["target_time_step"]),
            "target_time_min":     float(CFG["speedup"]["target_time_min"]),
            "lives":               int(CFG["lives"]),
            "glitch_enabled":      bool(CFG.get("effects", {}).get("glitch_enabled", True)),
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
    
    def _build_rule_fonts(self):
        c = int(CFG["rules"].get("banner_font_center", 64))
        p = int(CFG["rules"].get("banner_font_pinned", 40))
        self.rule_font_center = pygame.font.Font(FONT_PATH, c)
        self.rule_font_pinned = pygame.font.Font(FONT_PATH, p)

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
    
    def trigger_glitch(self, mag: float = 1.0, duration: float = GLITCH_DURATION):
        if not self.settings.get("glitch_enabled", True):
            return
             
        now = self.now()
        self.glitch_mag = max(0.0, mag)
        self.glitch_active_until = now + max(0.01, duration)
        self.glitch_start_time = now
        self.trigger_shake()

        if random.random() < 0.5:
            self.trigger_text_glitch()
    
    def _apply_glitch_effect(self, frame: pygame.Surface) -> pygame.Surface:
        if not self.settings.get("glitch_enabled", True):
            return frame
        
        now = self.now()        
        if now >= self.glitch_active_until:
            return frame

        dur = max(1e-6, GLITCH_DURATION)
        t = 1.0 - (self.glitch_active_until - now) / dur          
        vigor = (1 - abs(0.5 - t) * 2)                                 
        strength = max(0.0, min(1.0, vigor * self.glitch_mag))

        # 1) pixelation
        pf = GLITCH_PIXEL_FACTOR_MAX * strength
        if pf > 0:
            sw, sh = max(1, int(self.w * (1 - pf))), max(1, int(self.h * (1 - pf)))
            small = pygame.transform.smoothscale(frame, (sw, sh))
            frame = pygame.transform.scale(small, (self.w, self.h))

        out = frame.copy()

        # 2) RGB split
        ch_off = int(6 * strength) + random.randint(0, 2)
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
                dx = random.randint(-int(self.w * 0.03 * strength), int(self.w * 0.03 * strength))
                slice_rect = pygame.Rect(0, y, self.w, band_h)
                slice_surf = out.subsurface(slice_rect).copy()
                out.blit(slice_surf, (dx, y))

        # 4) colored blocks
        if random.random() < 0.4 * strength:
            w = random.randint(self.w // 12, self.w // 4)
            h = random.randint(self.h // 24, self.h // 8)
            x = random.randint(0, max(0, self.w - w))
            y = random.randint(0, max(0, self.h - h))
            col = (random.randint(180, 255), random.randint(120, 255),
                   random.randint(120, 255), random.randint(40, 100))
            pygame.draw.rect(out, col, (x, y, w, h))

        return out

    def trigger_text_glitch(self, duration: float = TEXT_GLITCH_DURATION):
        if not self.settings.get("glitch_enabled", True):
            return
        
        now = self.now()
        self.text_glitch_active_until = now + max(0.05, duration)
        self.next_text_glitch_at = now + random.uniform(TEXT_GLITCH_MIN_GAP, TEXT_GLITCH_MAX_GAP)

    def is_text_glitch_active(self) -> bool:
        return self.now() < self.text_glitch_active_until

    def _maybe_start_text_glitch(self):
        if not self.settings.get("glitch_enabled", True):
            return
        
        now = self.now()
        if now >= self.next_text_glitch_at and not self.is_text_glitch_active():
            self.trigger_text_glitch()

    def _glitch_text(self, text: str) -> str:
        out_chars = []
        for ch in text:
            if ch.isspace():
                out_chars.append(ch)
            elif random.random() < TEXT_GLITCH_CHAR_PROB:
                out_chars.append(random.choice(TEXT_GLITCH_CHARSET))
            else:
                out_chars.append(ch)
        return "".join(out_chars)

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
            ("Glitch",        "ON" if self.settings.get('glitch_enabled', True) else "OFF", "glitch_enabled"),  # NOWE
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

    def toggle_settings(self):
        if self.scene is Scene.SETTINGS:
            self.settings_cancel()   
        elif self.scene is Scene.MENU: 
            self.open_settings()   

    def _settings_clamp(self):
        s = self.settings
        s["target_time_initial"] = max(0.2, min(10.0, float(s["target_time_initial"])))
        s["target_time_min"]     = max(0.1, min(float(s["target_time_initial"]), float(s["target_time_min"])) )
        s["target_time_step"]    = max(-1.0, min(1.0, float(s["target_time_step"])))
        s["lives"]               = max(1, min(9, int(s["lives"])))
        s["volume"]              = max(0.0, min(1.0, float(s["volume"])))
        s["timed_rule_bonus"]    = max(0.0, min(30.0, float(s["timed_rule_bonus"])))
        s["rule_font_center"] = max(8, min(200, int(s["rule_font_center"])))
        s["rule_font_pinned"] = max(8, min(200, int(s["rule_font_pinned"])))

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
        
        if key == "glitch_enabled":
            self.settings["glitch_enabled"] = not self.settings["glitch_enabled"]
            if not self.settings["glitch_enabled"]:
                self.glitch_active_until = 0.0
                self.text_glitch_active_until = 0.0
            return

        step = {
            "target_time_initial": 0.1,
            "target_time_step":    0.01,
            "target_time_min":     0.05,
            "lives":               1,
            "volume":              0.05,
            "timed_rule_bonus":    0.5,
            "rule_font_center":    2,     # NOWE
            "rule_font_pinned":    2,     # NOWE
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
            "glitch_enabled":      bool(CFG.get("effects", {}).get("glitch_enabled", True)),
            "volume":              float(CFG["audio"]["volume"]),
            "fullscreen":          bool(CFG["display"]["fullscreen"]),
            "timed_rule_bonus":    float(CFG["timed"].get("rule_bonus", 5.0)),
            "rule_font_center": int(CFG["rules"].get("banner_font_center", 64)),
            "rule_font_pinned": int(CFG["rules"].get("banner_font_pinned", 40)),

        })
        self.settings_idx = 0
        self.settings_move(0)
        self.trigger_glitch(mag=1.0)
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
        CFG["effects"] = CFG.get("effects", {})
        CFG["effects"]["glitch_enabled"] = bool(s["glitch_enabled"])
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
                        "effects": {
                "glitch_enabled": CFG["effects"]["glitch_enabled"],
            },
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
                "banner_font_center": CFG["rules"]["banner_font_center"], 
                "banner_font_pinned": CFG["rules"]["banner_font_pinned"], 
            },
            "highscore": CFG.get("highscore", 0),
        })
        if self.music_ok:
            pygame.mixer.music.set_volume(float(CFG["audio"]["volume"]))
        self._set_display_mode(bool(CFG["display"]["fullscreen"]))
        self._build_rule_fonts()
        self.trigger_glitch(mag=1.0)
        self.scene = Scene.MENU

    def settings_cancel(self):
        self.trigger_glitch(mag=1.0)
        self.scene = Scene.MENU

    # ----- gameplay flow -----
    def reset_game_state(self):
        self.score = 0
        self.streak = 0
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
        was_pinned = (self.rule is not None and self.now() >= self.rule_banner_until)
        a = random.choice(SYMS)
        b = random.choice([s for s in SYMS if s != a])
        if self.rule == (a, b):
            b = random.choice([s for s in SYMS if s not in (a, b)])
        self.rule = (a, b)

        now = self.now()
        self.rule_banner_from_pinned = was_pinned  # <-- KLUCZOWE
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
            self.streak += 1
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
            self.lock_until_all_released = True
            self.accept_after = self.now() + 0.12
        else:
            self.streak = 0
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
        self._maybe_start_text_glitch()

        if self.lock_until_all_released and not self.keys_down and now >= self.accept_after:
            self.lock_until_all_released = False     

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
            self.streak = 0
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

            if event.key == pygame.K_o:
                if self.scene in (Scene.MENU, Scene.SETTINGS):
                    self.toggle_settings()
                    return

            if self.scene is Scene.MENU:
                if event.key == pygame.K_RETURN:
                    self.start_game()
                elif event.key == pygame.K_m:
                    self.mode = (Mode.TIMED if self.mode is Mode.SPEEDUP else Mode.SPEEDUP)

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
            
            self.keys_down.add(event.key)

            name = keymap.get(event.key)
            if name:
                if self.lock_until_all_released or self.now() < getattr(self, 'accept_after', 0.0):
                    return
                iq.push(name)
        elif event.type == pygame.KEYUP:
            self.keys_down.discard(event.key)
            if self.lock_until_all_released and not self.keys_down and self.now() >= getattr(self, 'accept_after', 0.0):
                self.lock_until_all_released = False

    # ----- rendering -----
    def draw_text(self, font, text, pos, color=INK, shadow=True):
        render_text = self._glitch_text(text) if self.is_text_glitch_active() else text

        if shadow:
            shadow_surf = font.render(render_text, True, (0, 0, 0))
            self.screen.blit(shadow_surf, (pos[0] + 2, pos[1] + 2))
        txt_surf = font.render(render_text, True, color)
        self.screen.blit(txt_surf, pos)

    def _draw_timer_bar_bottom(self, ratio: float, label: Optional[str] = None):
        ratio = max(0.0, min(1.0, ratio))
        if ratio <= TIMER_BAR_CRIT_TIME:   fill_color = TIMER_BAR_CRIT_COLOR
        elif ratio <= TIMER_BAR_WARN_TIME: fill_color = TIMER_BAR_WARN_COLOR
        else:                              fill_color = TIMER_BAR_FILL

        bar_w = int(self.w * TIMER_BAR_WIDTH_FACTOR)
        bar_h = int(TIMER_BAR_HEIGHT)
        bar_x = (self.w - bar_w) // 2
        bottom_margin = int(self.h * TIMER_BOTTOM_MARGIN_FACTOR)
        bar_y = self.h - bottom_margin - bar_h

        # tło paska
        pygame.draw.rect(self.screen, TIMER_BAR_BG,
                         (bar_x, bar_y, bar_w, bar_h),
                         border_radius=TIMER_BAR_BORDER_RADIUS)

        # wypełnienie
        fill_w = int(bar_w * ratio)
        if fill_w > 0:
            pygame.draw.rect(self.screen, fill_color,
                             (bar_x, bar_y, fill_w, bar_h),
                             border_radius=TIMER_BAR_BORDER_RADIUS)

        # ramka
        pygame.draw.rect(self.screen, TIMER_BAR_BORDER,
                         (bar_x, bar_y, bar_w, bar_h),
                         width=TIMER_BAR_BORDER_W,
                         border_radius=TIMER_BAR_BORDER_RADIUS)

        # --- NOWE: pionowy indykator aktualnej pozycji timera ---
        indicator_x = bar_x + fill_w
        ind_w = int(TIMER_POSITION_INDICATOR_W)
        ind_pad = int(TIMER_POSITION_INDICATOR_PAD)
        # upewnij się, że kreska jest zawsze widoczna w granicach paska
        indicator_x = max(bar_x, min(bar_x + bar_w, indicator_x))
        indicator_rect = pygame.Rect(indicator_x - ind_w // 2,
                                     bar_y - ind_pad,
                                     ind_w,
                                     bar_h + ind_pad * 2)
        pygame.draw.rect(self.screen, ACCENT, indicator_rect)

        # --- ZMIANA: label nad paskiem ---
        if label:
            timer_font = getattr(self, "timer_font", self.mid)
            lw, lh = timer_font.size(label)
            tx = bar_x + (bar_w - lw) // 2
            ty = bar_y - lh - TIMER_LABEL_GAP
            # cień + tekst
            shadow_surf = timer_font.render(label, True, (0, 0, 0))
            self.screen.blit(shadow_surf, (tx + 2, ty + 2))
            txt_surf = timer_font.render(label, True, TIMER_BAR_TEXT_COLOR)
            self.screen.blit(txt_surf, (tx, ty))

    def draw_symbol(self, surface: pygame.Surface, name: str, rect: pygame.Rect):
        path = self.cfg["images"].get(f"symbol_{name.lower()}")
        img = self.images.load(path)
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

    def draw_arrow(self, surface: pygame.Surface, rect: pygame.Rect,
                   color=RULE_ARROW_COLOR, width=RULE_ARROW_W):
        path = self.cfg.get("images", {}).get("arrow")
        img = self.images.load(path) if path else None
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

    def draw_chip(self, text: str, x: int, y: int,
                pad: int = 10, radius: int = 10,
                bg=(20, 22, 30, 160), border=(120, 200, 255, 220),
                text_color=INK, *, font: Optional[pygame.font.Font] = None):
        fnt = font or self.font
        t_surf = fnt.render(text, True, text_color)
        w, h = t_surf.get_width() + pad*2, t_surf.get_height() + pad*2

        chip = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(chip, bg, chip.get_rect(), border_radius=radius)
        pygame.draw.rect(chip, border, chip.get_rect(), width=1, border_radius=radius)
        
        shadow = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 120), shadow.get_rect(), border_radius=radius+2)
        self.screen.blit(shadow, (x+3, y+4))

        chip.blit(t_surf, (pad, pad))
        self.screen.blit(chip, (x, y))
        return pygame.Rect(x, y, w, h)

    def _draw_hud(self):
        top_y = int(self.h * HUD_TOP_MARGIN_FACTOR)
        side_pad_x = int(self.w * PADDING)
        gap = 10

        # left chip: STREAK
        left_rect = self.draw_chip(f"Streak: {self.streak}", side_pad_x, top_y)

        # right chip: HIGHSCORE
        hs_text = f"Highscore: {self.highscore}"
        # temp render to know width with small font
        hs_rect = self.draw_chip(hs_text, 0, -1000)   # offscreen; we don't keep it
        hs_w, hs_h = hs_rect.size
        right_x = self.w - side_pad_x - hs_w
        right_rect = self.draw_chip(hs_text, right_x, top_y)

        # center chip: SCORE (bigger font)
        score_text = f"Score: {self.score}"
        # estimate centered using mid font inside chip
        tmp = self.mid.render(score_text, True, INK)
        score_w = tmp.get_width() + 20
        score_h = tmp.get_height() + 20
        cx = (self.w - score_w) // 2
        center_rect = self.draw_chip(score_text, cx, top_y, font=self.mid)

        # remember where the top bar ends; the rule banner docks below this
        bar_h = max(left_rect.height, center_rect.height, right_rect.height)
        self._topbar_bottom_y = top_y + bar_h + int(self.h * 0.02)

        # --- Timer bar (bottom) ---
        if self.scene is Scene.GAME:
            if self.mode is Mode.TIMED:
                self._draw_timer_bar_bottom(self.time_left / TIMED_DURATION, f"{self.time_left:.1f}s")
            elif self.mode is Mode.SPEEDUP and self.target_deadline is not None and self.target_time > 0:
                remaining = max(0.0, self.target_deadline - self.now())
                ratio = remaining / max(0.001, self.target_time)
                self._draw_timer_bar_bottom(ratio, f"{remaining:.1f}s")

    def _ease_out_cubic(self, t: float) -> float:
        t = max(0.0, min(1.0, t)); return 1 - (1 - t) ** 3

    def _render_rule_panel_surface(self, panel_scale: float, symbol_scale: float, y_bias: float = 0.0, *, label_font: Optional[pygame.font.Font] = None):
        panel_scale = max(0.2, panel_scale)
        symbol_scale = max(0.2, symbol_scale)

        panel_w = int(self.w * RULE_PANEL_W_FACTOR * panel_scale)
        panel_h = int(self.h * RULE_PANEL_H_FACTOR * panel_scale)

        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        shadow = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0,0,0,120), shadow.get_rect(), border_radius=RULE_PANEL_RADIUS+2)

        pygame.draw.rect(panel, RULE_PANEL_BG, panel.get_rect(), border_radius=RULE_PANEL_RADIUS)
        pygame.draw.rect(panel, RULE_PANEL_BORDER, panel.get_rect(), width=RULE_PANEL_BORDER_W, border_radius=RULE_PANEL_RADIUS)

        # --- ikony ---
        icon_size = int(self.w * RULE_ICON_SIZE_FACTOR * panel_scale * symbol_scale)
        gap = int(self.w * RULE_ICON_GAP_FACTOR * panel_scale * symbol_scale)

        cx = panel_w // 2
        cy = int(panel_h * 0.5 + panel_h * y_bias)

        left_rect  = pygame.Rect(0, 0, icon_size, icon_size)
        right_rect = pygame.Rect(0, 0, icon_size, icon_size)
        arrow_w = int(icon_size * 1.05); arrow_h = int(icon_size * 0.55)
        arrow_rect = pygame.Rect(0, 0, arrow_w, arrow_h); arrow_rect.center = (cx, cy)
        left_rect.center  = (cx - (arrow_rect.width // 2) - gap - icon_size // 2, cy)
        right_rect.center = (cx + (arrow_rect.width // 2) + gap + icon_size // 2, cy)

        self.draw_symbol(panel, self.rule[0], left_rect)
        self.draw_arrow(panel, arrow_rect)
        self.draw_symbol(panel, self.rule[1], right_rect)

        fnt = label_font or self.mid
        label = fnt.render(f"RULE: {self.rule[0]} -> {self.rule[1]}", True, ACCENT)
        panel.blit(label, ((panel_w - label.get_width()) // 2, max(8, cy - icon_size//2 - label.get_height() - RULE_BANNER_LABEL_GAP)))
        return panel, shadow

    def _draw_rule_banner_anim(self):
        now = self.now()
        t = now - self.rule_banner_anim_start
        if t < 0:
            t = 0
        if t > RULE_BANNER_TOTAL_SEC:
            t = RULE_BANNER_TOTAL_SEC

        if t <= RULE_BANNER_IN_SEC:
            # FAZA WJAZDU
            p = self._ease_out_cubic(t / RULE_BANNER_IN_SEC)

            if getattr(self, "rule_banner_from_pinned", False):
                # start z doku -> środek
                start_scale  = RULE_BANNER_PIN_SCALE
                end_scale    = 1.0
                start_sym    = RULE_SYMBOL_SCALE_PINNED
                end_sym      = RULE_SYMBOL_SCALE_CENTER
                start_bias   = RULE_SYMBOL_Y_OFFSET_PINNED
                end_bias     = RULE_SYMBOL_Y_OFFSET_CENTER

                panel_scale  = start_scale + (end_scale - start_scale) * p
                symbol_scale = start_sym   + (end_sym   - start_sym)   * p
                y_bias       = start_bias  + (end_bias  - start_bias)  * p

                # UŻYJEMY FONTU "CENTER" PODCZAS CAŁEGO WJAZDU
                panel, shadow = self._render_rule_panel_surface(
                    panel_scale, symbol_scale, y_bias, label_font=self.rule_font_center
                )
                panel_w, panel_h = panel.get_size()

                pinned_y = int(getattr(self, "_topbar_bottom_y", self.h * HUD_TOP_MARGIN_FACTOR))
                mid_y    = int(self.h * 0.30)
                y = int(pinned_y + (mid_y - pinned_y) * p)

            else:
                # wjazd z góry do środka (bez pochodzenia z doku)
                panel_scale = 1.0
                symbol_scale = RULE_SYMBOL_SCALE_CENTER
                y_bias = RULE_SYMBOL_Y_OFFSET_CENTER
                panel, shadow = self._render_rule_panel_surface(
                    panel_scale, symbol_scale, y_bias, label_font=self.rule_font_center
                )
                panel_w, panel_h = panel.get_size()
                start_y = -panel_h
                mid_y = int(self.h * 0.30)
                y = int(start_y + (mid_y - start_y) * p)

        elif t <= RULE_BANNER_IN_SEC + RULE_BANNER_HOLD_SEC:
            # FAZA HOLD – NA ŚRODKU
            panel_scale = 1.0
            symbol_scale = RULE_SYMBOL_SCALE_CENTER
            y_bias = RULE_SYMBOL_Y_OFFSET_CENTER
            panel, shadow = self._render_rule_panel_surface(
                1.0, RULE_SYMBOL_SCALE_CENTER, 0.0, label_font=self.rule_font_center
            )
            panel_w, panel_h = panel.get_size()
            y = int(self.h * 0.30)
            # resetujemy flagę po dotarciu do środka
            self.rule_banner_from_pinned = False

        else:
            # FAZA WYJAZDU DO GÓRY (DOKOWANIE)
            tt = (t - RULE_BANNER_IN_SEC - RULE_BANNER_HOLD_SEC) / max(0.001, RULE_BANNER_TO_TOP_SEC)
            p = self._ease_out_cubic(tt)

            panel_scale  = 1.0 + (RULE_BANNER_PIN_SCALE - 1.0) * p
            symbol_scale = (RULE_SYMBOL_SCALE_CENTER
                            + (RULE_SYMBOL_SCALE_PINNED - RULE_SYMBOL_SCALE_CENTER) * p)
            y_bias       = (RULE_SYMBOL_Y_OFFSET_CENTER
                            + (RULE_SYMBOL_Y_OFFSET_PINNED - RULE_SYMBOL_Y_OFFSET_CENTER) * p)

            # TU JUŻ UŻYWAMY FONTU "PINNED"
            panel, shadow = self._render_rule_panel_surface(
                panel_scale, symbol_scale, y_bias, label_font=self.rule_font_pinned
            )
            panel_w, panel_h = panel.get_size()

            mid_y    = int(self.h * 0.30)
            pinned_y = int(getattr(self, "_topbar_bottom_y", self.h * HUD_TOP_MARGIN_FACTOR))
            y = int(mid_y + (pinned_y - mid_y) * p)

        panel_x = (self.w - panel_w) // 2
        self.screen.blit(shadow, (panel_x + 3, y + 5))
        self.screen.blit(panel, (panel_x, y))

    def _draw_rule_banner_pinned(self):
        if not self.rule:
            return
        panel_scale  = RULE_BANNER_PIN_SCALE
        symbol_scale = RULE_SYMBOL_SCALE_PINNED
        y_bias       = RULE_SYMBOL_Y_OFFSET_PINNED

        # ZAWSZE FONT "PINNED" W DOKU
        panel, shadow = self._render_rule_panel_surface(
            panel_scale, symbol_scale, y_bias, label_font=self.rule_font_pinned
        )
        panel_w, panel_h = panel.get_size()
        panel_x = (self.w - panel_w) // 2

        # dock tuż pod górnym HUDem (fallback, gdy brak zapisanego wymiaru)
        panel_y = int(getattr(self, "_topbar_bottom_y", self.h * HUD_TOP_MARGIN_FACTOR))

        self.screen.blit(shadow, (panel_x + 3, panel_y + 5))
        self.screen.blit(panel, (panel_x, panel_y))

    def _draw_spawn_animation(self, surface: pygame.Surface, name: str, rect: pygame.Rect):
        age   = self.now() - self.symbol_spawn_time
        t     = 0.0 if SYMBOL_ANIM_TIME <= 0 else min(1.0, max(0.0, age / SYMBOL_ANIM_TIME))
        eased = 1.0 - (1.0 - t) ** 3

        base_size = self.w * SYMBOL_BASE_SIZE_FACTOR
        scale     = SYMBOL_ANIM_START_SCALE + (1.0 - SYMBOL_ANIM_START_SCALE) * eased
        size      = base_size * scale

        start_y = self.h * (0.5 + SYMBOL_ANIM_OFFSET_Y)
        end_y   = self.h * 0.5
        cy      = start_y + (end_y - start_y) * eased

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

        self.draw_symbol(surface, name, draw_rect)

    def _draw_gameplay(self):
        if self.bg_img: self.screen.blit(self.bg_img, (0, 0))
        else:           self.screen.fill(BG)

        self._draw_hud()

        if self.rule and self.now() >= self.rule_banner_until:
            self._draw_rule_banner_pinned()

        if self.target:
            base_rect = pygame.Rect(0, 0, self.w * SYMBOL_BASE_SIZE_FACTOR, self.w * SYMBOL_BASE_SIZE_FACTOR)
            base_rect.center = (self.w * 0.5, self.h * 0.5)
            self._draw_spawn_animation(self.screen, self.target, base_rect)
    
    def draw(self):
        self.fb.fill((0, 0, 0, 0))
        old_screen = self.screen
        self.screen = self.fb
        try:
            if self.scene is Scene.GAME and self.rule and self.now() < self.rule_banner_until:
                if self.bg_img:
                    self.screen.blit(self.bg_img, (0, 0))
                else:
                    self.screen.fill(BG)
                self._draw_rule_banner_anim()

            elif self.scene is Scene.GAME:
                self._draw_gameplay()

            elif self.scene is Scene.MENU:
                if self.bg_img:
                    self.screen.blit(self.bg_img, (0, 0))
                else:
                    self.screen.fill(BG)
                title_text = "4-Symbols"
                tw, th = self.big.size(title_text)
                tx = self.w / 2 - tw / 2
                ty = self.h * MENU_TITLE_Y_FACTOR
                self.draw_text(self.big, title_text, (tx, ty))

                mode_label = "SPEED-UP" if self.mode is Mode.SPEEDUP else "TIMED"
                mode_text = f"Mode: {mode_label}  (M = change)"
                mw, mh = self.mid.size(mode_text)
                self.draw_text(self.mid, mode_text, (self.w / 2 - mw / 2, ty + th + MENU_MODE_GAP), color=ACCENT)

                hint_text = "ENTER = start   ·   ESC/Q = quit"
                hw, hh = self.font.size(hint_text)
                self.draw_text(self.font, hint_text,
                            (self.w / 2 - hw / 2, ty + th + MENU_HINT_GAP + mh))

                hint2_text = "O = settings"
                h2w, h2h = self.font.size(hint2_text)
                self.draw_text(self.font, hint2_text,
                            (self.w / 2 - h2w / 2,
                                ty + th + MENU_HINT_GAP + mh + hh + MENU_HINT2_EXTRA_GAP))

            elif self.scene is Scene.OVER:
                if self.bg_img:
                    self.screen.blit(self.bg_img, (0, 0))
                else:
                    self.screen.fill(BG)

                over_text = "GAME OVER"
                ow, oh = self.big.size(over_text)
                self.draw_text(self.big, over_text,
                            (self.w / 2 - ow / 2, self.h / 2 - oh / 2 + OVER_TITLE_OFFSET_Y))

                score_text = f"Score: {self.score}"
                best_text = f"Best:  {self.highscore}"
                sw, sh = self.mid.size(score_text)
                bw, bh = self.mid.size(best_text)
                self.draw_text(self.mid, score_text,
                            (self.w / 2 - sw / 2, self.h / 2 - sh / 2 + OVER_SCORE_GAP1), color=ACCENT)
                self.draw_text(self.mid, best_text,
                            (self.w / 2 - bw / 2, self.h / 2 - bh / 2 + OVER_SCORE_GAP2), color=ACCENT)

                info_text = "SPACE = play again   ·   ESC = quit"
                iw, ih = self.font.size(info_text)
                self.draw_text(self.font, info_text, (self.w / 2 - iw / 2, self.h / 2 + OVER_INFO_GAP))

            elif self.scene is Scene.SETTINGS:
                if self.bg_img:
                    self.screen.blit(self.bg_img, (0, 0))
                else:
                    self.screen.fill(BG)

                title_text = "Settings"
                tw, th = self.big.size(title_text)
                self.draw_text(self.big, title_text,
                            (self.w / 2 - tw / 2, self.h * SETTINGS_TITLE_Y_FACTOR))

                y = self.h * SETTINGS_LIST_Y_START_FACTOR
                for i, (label, value, key) in enumerate(self.settings_items()):
                    item_text = f"{label}: {value}"
                    color = ACCENT if (i == self.settings_idx and key is not None) else INK
                    iw, ih = self.mid.size(item_text)
                    self.draw_text(self.mid, item_text, (self.w / 2 - iw / 2, y), color=color)
                    y += ih + SETTINGS_ITEM_SPACING

                help1 = "↑/↓ select · ←/→ adjust · R reset high score"
                help2 = "ENTER save · ESC back"
                w1, h1 = self.font.size(help1)
                w2, h2 = self.font.size(help2)
                self.draw_text(self.font, help1, (self.w / 2 - w1 / 2, y + SETTINGS_HELP_MARGIN_TOP))
                self.draw_text(self.font, help2,
                            (self.w / 2 - w2 / 2, y + SETTINGS_HELP_MARGIN_TOP + h1 + SETTINGS_HELP_GAP))
        finally:
            self.screen = old_screen

        final_surface = self._apply_glitch_effect(self.fb)
        self.screen.blit(final_surface, (0, 0))
        pygame.display.flip()

# ========= MAIN LOOP =========
def main():
    os.environ['SDL_VIDEO_WINDOW_POS'] = "0,0"

    pygame.init()
    pygame.key.set_repeat()
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
