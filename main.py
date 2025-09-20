from __future__ import annotations
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, Optional, Tuple, List

import pygame

# ========= CONFIG =========

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULT_CFG = {
    "pins": {"CIRCLE": 17, "CROSS": 27, "SQUARE": 22, "TRIANGLE": 23},
    "display": {"fullscreen": True, "fps": 60, "windowed_size": [720, 1280]},
    "speedup": {"target_time_initial": 3, "target_time_min": 0.45, "target_time_step": -0.03},
    "timed": {"duration": 60.0, "rule_bonus": 5.0},
    "rules": {"every_hits": 10, "banner_sec": 2.0, "banner_font_center": 64, "banner_font_pinned": 40},
    "lives": 3,
    "audio": {"music": "assets/music.ogg", "volume": 0.5},
    "effects": {"glitch_enabled": True},
    "images": {
        "background": "assets/images/bg.png",
        "symbol_circle": "assets/images/circle.png",
        "symbol_cross": "assets/images/cross.png",
        "symbol_square": "assets/images/square.png",
        "symbol_triangle": "assets/images/triangle.png",
        "arrow": "assets/images/arrow.png",
    },
    "highscore": 0,
}

def _deepcopy(obj):
    return json.loads(json.dumps(obj))

def _merge(dst: dict, src: dict) -> dict:
    """Shallow+recursive merge for dict trees (src overrides dst)."""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v
    return dst

def _sanitize_cfg(cfg: dict) -> dict:
    """Clamp user config into safe/expected ranges."""
    s = cfg["speedup"]
    s["target_time_initial"] = float(max(0.2, min(10.0, s["target_time_initial"])))
    s["target_time_min"] = float(max(0.1, min(s["target_time_initial"], s["target_time_min"])))
    s["target_time_step"] = float(max(-1.0, min(1.0, s["target_time_step"])))

    cfg["lives"] = int(max(0, min(9, cfg["lives"])))
    cfg["audio"]["volume"] = float(max(0.0, min(1.0, cfg["audio"]["volume"])))

    if "fps" in cfg["display"]:
        cfg["display"]["fps"] = int(max(30, min(240, cfg["display"]["fps"])))

    # windowed size
    ws = cfg["display"].get("windowed_size", [720, 1280])
    if (
        isinstance(ws, (list, tuple))
        and len(ws) == 2
        and all(isinstance(x, (int, float)) for x in ws)
    ):
        w, h = int(ws[0]), int(ws[1])
        w = max(200, min(10000, w))
        h = max(200, min(10000, h))
        cfg["display"]["windowed_size"] = [w, h]
    else:
        cfg["display"]["windowed_size"] = [720, 1280]

    # rules
    r = cfg.setdefault("rules", {})
    r["banner_font_center"] = int(max(8, min(200, r.get("banner_font_center", 64))))
    r["banner_font_pinned"] = int(max(8, min(200, r.get("banner_font_pinned", 40))))
    return cfg

def save_config(partial_cfg: dict) -> None:
    """Persist only the provided keys (merge semantics)."""
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

def _persist_windowed_size(width: int, height: int) -> None:
    """Store last windowed size back to config for next run."""
    try:
        CFG.setdefault("display", {})
        CFG["display"]["windowed_size"] = [int(width), int(height)]
        save_config({"display": {"windowed_size": CFG["display"]["windowed_size"]}})
    except Exception:
        pass

# ========= IMAGE LOADER (cache) =========

class ImageStore:
    """Tiny image cache so we don't reload the same texture repeatedly."""

    def __init__(self) -> None:
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
            # Fail silently – caller can draw a vector fallback.
            return None

    def clear(self) -> None:
        self.cache.clear()

IMAGES = ImageStore()

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


PINS = Pins(**CFG["pins"])  # typed view over pin integers


class InputQueue:
    """Simple FIFO for button/keyboard symbol inputs."""

    def __init__(self) -> None:
        self._q: list[str] = []

    def push(self, name: str) -> None:
        self._q.append(name)

    def pop_all(self) -> list[str]:
        out = self._q[:]
        self._q.clear()
        return out

# ========= CONSTANTS =========
# Kolory bazowe UI / tła
BG = (8, 10, 12)                 # kolor tła sceny, gdy brak obrazka bg
PAD = (40, 44, 52)               # kolor płytek/paneli neutralnych (nieużywane teraz – zostawione na przyszłość)
PAD_HI = (90, 200, 255)          # kolor podświetlenia płytek/paneli
PAD_GOOD = (60, 200, 120)        # kolor akcji poprawnej
PAD_BAD = (220, 80, 80)          # kolor akcji błędnej
INK = (235, 235, 235)            # podstawowy kolor tekstu
ACCENT = (255, 210, 90)          # akcent (nagłówki, ważne etykiety)

# Kolory wektorowych symboli, jeśli brak tekstur PNG
SYMBOL_COLORS = {
    "TRIANGLE": (0, 255, 0),
    "CIRCLE": (255, 0, 0),
    "CROSS": (0, 0, 255),
    "SQUARE": (255, 215, 0),
}

# Ogólne odstępy/układ
PADDING = 0.06                   # margines sceny (proporcja szer./wys. okna)
GAP = 0.04                       # przerwa między obiektami w siatce
FPS = CFG["display"]["fps"]      # docelowy FPS (z configu)

# --- Levels --- (progresja poziomów)
LEVEL_GOAL_PER_LEVEL = 15        # ile trafień, by wskoczyć na kolejny poziom
LEVEL_MAX = 5                    # maks. zdefiniowany poziom (na przyszłość)
LEVELS_ACTIVE_FOR_NOW = 5        # faktycznie używana liczba poziomów

LEVEL_COLORS = {                 # kolor wyniku (kapsuła) per poziom
    1: (235, 235, 235),
    2: (60, 200, 120),
}

# Tempo gry i tryby
TARGET_TIME_INITIAL = CFG["speedup"]["target_time_initial"]  # startowy czas na reakcję (tryb SPEEDUP)
TARGET_TIME_MIN = CFG["speedup"]["target_time_min"]          # dolne ograniczenie czasu reakcji
TARGET_TIME_STEP = CFG["speedup"]["target_time_step"]        # zmiana czasu po każdym trafieniu
TIMED_DURATION = CFG["timed"]["duration"]                    # czas całej rundy w trybie TIMED
RULE_EVERY_HITS = CFG["rules"]["every_hits"]                 # co ile trafień losujemy nową regułę (poziom 2+)
RULE_BANNER_SEC = CFG["rules"]["banner_sec"]                 # (pozostawione dla kompatybilności)
MAX_LIVES = CFG["lives"]                                     # liczba żyć w SPEEDUP (jeśli >0)
ADDITIONAL_RULE_TIME = float(CFG["timed"].get("rule_bonus", 5.0))  # bonus sekund po wylosowaniu reguły (TIMED)

# Rozmiar i animacja symbolu celu
SYMBOL_BASE_SIZE_FACTOR = 0.26    # bazowy rozmiar symbolu (proporcja szerokości okna)
SYMBOL_ANIM_TIME = 0.30           # czas dojścia animacji skali/pozycji do 100%
SYMBOL_ANIM_START_SCALE = 0.20    # początkowa skala podczas spawn
SYMBOL_ANIM_OFFSET_Y = 0.08       # startowe przesunięcie w dół (proporcja wysokości)

# Efekt potrząśnięcia (shake) kamery
SHAKE_DURATION = 0.12             # długość wstrząsu
SHAKE_AMPLITUDE_FACT = 0.012      # amplituda (proporcja szerokości okna)
SHAKE_FREQ_HZ = 18.0              # częstotliwość drgań

# Ogólne zaokrąglenie rogów UI
UI_RADIUS = 8

# Parametry rysowania symboli wektorowych (fallback)
SYMBOL_DRAW_THICKNESS = 20        # grubość linii
SYMBOL_SQUARE_RADIUS = UI_RADIUS  # promień zaokrąglenia kwadratu
SYMBOL_CIRCLE_RADIUS_FACTOR = 0.32        # promień koła względem mniejszego boku recta
SYMBOL_TRIANGLE_POINT_FACTOR = 0.9        # „ostrość” trójkąta
SYMBOL_CROSS_K_FACTOR = 1.0               # długość ramion krzyżyka (krotność promienia)

# HUD (górny pasek)
HUD_TOP_MARGIN_FACTOR = 0.02      # dodatkowy margines pod topbarem (dokowanie banera reguł)
HUD_SEPARATOR = "   ·   "         # separator tekstowy

# --- Glitch --- (efekt post-process)
GLITCH_DURATION = 0.20            # długość pojedynczego glitcha
GLITCH_PIXEL_FACTOR_MAX = 0.10    # maks. pikselizacja (skala downsample)
GLITCH_FREQ_HZ = 60.0             # tempo migotania/glitchowania pasów

# --- Text Glitch --- (zakłócenia napisów)
TEXT_GLITCH_DURATION = 0.5        # jak długo trwa glitch tekstu
TEXT_GLITCH_MIN_GAP = 1           # min przerwa między glitchami
TEXT_GLITCH_MAX_GAP = 5.0         # max przerwa między glitchami
TEXT_GLITCH_CHAR_PROB = 0.01      # prawdopodobieństwo podmiany znaku
TEXT_GLITCH_CHARSET = "01+-_#@$%&*[]{}<>/\\|≈≠∆░▒▓"  # z jakich znaków mieszamy

# --- Spawn anim --- (dodatkowe efekty przy pojawieniu symbolu)
SYMBOL_SPAWN_ANIM_DURATION = 0.40       # łączny czas animacji „pojawienia”
SYMBOL_SPAWN_GLITCH_DURATION = 0.02     # krótki glitch przy spawnie
SYMBOL_SPAWN_GLOW_MAX_ALPHA = 20        # maks. intensywność poświaty
SYMBOL_SPAWN_GLOW_RADIUS_FACTOR = 1.15  # promień poświaty względem symbolu

# --- Pulse ---
PULSE_DURATION = 0.30           # ~0.3 s
PULSE_MAX_SCALE = 1.18          # ile maksymalnie powiększamy

# --- Timer bar (bottom) --- (pasek czasu na dole ekranu)
TIMER_BAR_WIDTH_FACTOR = 0.60     # szerokość paska względem szerokości okna
TIMER_BAR_HEIGHT = 18             # wysokość paska w px
TIMER_BAR_MARGIN_TOP = 10         # wewnętrzny margines (niewykorzystywany – zachowany)
TIMER_BAR_BG = (40, 40, 50)       # kolor tła paska
TIMER_BAR_FILL = (90, 200, 255)   # kolor wypełnienia (normalny)
TIMER_BAR_BORDER = (160, 180, 200)# kolor ramki
TIMER_BAR_BORDER_W = 2            # grubość ramki
TIMER_BAR_WARN_COLOR = (255, 170, 80)  # kolor ostrzegawczy (mało czasu)
TIMER_BAR_CRIT_COLOR = (220, 80, 80)   # kolor krytyczny (bardzo mało czasu)
TIMER_BAR_WARN_TIME = 0.50        # próg ostrzegawczy (ułamek 0–1)
TIMER_BAR_CRIT_TIME = 0.25        # próg krytyczny (ułamek 0–1)
TIMER_BAR_BORDER_RADIUS = UI_RADIUS     # zaokrąglenie rogów paska
TIMER_BOTTOM_MARGIN_FACTOR = 0.03 # odległość paska od dołu ekranu (proporcja wys.)
TIMER_BAR_TEXT_COLOR = INK        # kolor tekstu nad paskiem
TIMER_FONT_SIZE = 48              # bazowy rozmiar czcionki timera (skaluje się w kodzie)
TIMER_POSITION_INDICATOR_W = 4    # szerokość pionowego markera pozycji
TIMER_POSITION_INDICATOR_PAD = 3  # pionowe „wystawanie” markera poza pasek
TIMER_LABEL_GAP = 8               # odstęp tekstu od paska

# --- Rule banner --- (baner z nową regułą)
RULE_BANNER_PINNED_MARGIN = 25    # px odstępu bannera od kapsuły SCORE
RULE_BANNER_IN_SEC = 0.35         # czas wejścia banera (z góry)
RULE_BANNER_HOLD_SEC = 2.0        # czas utrzymania w centrum
RULE_BANNER_TO_TOP_SEC = 0.35     # czas wyjścia/dokowania do topu
RULE_BANNER_TOTAL_SEC = RULE_BANNER_IN_SEC + RULE_BANNER_HOLD_SEC + RULE_BANNER_TO_TOP_SEC
RULE_PANEL_BG = (22, 26, 34, 110) # tło panelu banera (z alpha)
RULE_PANEL_BORDER = (120, 200, 255)     # obrys panelu
RULE_PANEL_BORDER_W = 3           # grubość obrysu
RULE_PANEL_RADIUS = 30            # promień rogów panelu
RULE_ICON_SIZE_FACTOR = 0.1       # rozmiar symboli w banerze (proporcja szerokości ekranu)
RULE_ICON_GAP_FACTOR = 0.04       # odstęp między symbolami/strzałką
RULE_ARROW_W = 6                  # grubość strzałki (wektor fallback)
RULE_ARROW_COLOR = (200, 220, 255)# kolor strzałki (fallback)
RULE_PANEL_PAD = 16               # wewnętrzny padding panelu
RULE_BANNER_VGAP = 8              # pionowe odstępy tytuł/ikony
RULE_BANNER_TITLE = "REMAPPING:"   # tekst tytułu banera
RULE_BANNER_PIN_SCALE = 0.50      # skala panelu po „zadokowaniu” u góry
RULE_SYMBOL_SCALE_CENTER = 1.00   # skala symboli w centrum
RULE_SYMBOL_SCALE_PINNED = 0.70   # skala symboli po dokowaniu
RULE_BANNER_MIN_W_FACTOR = 0.80   # minimalna szerokość panelu względem ekranu

# --- Memory (ring hide conditions) ---
MEMORY_HIDE_AFTER_MOVES = 4      # po ilu ruchach znikają ikony
MEMORY_HIDE_AFTER_SEC   = 5.0    # po ilu sekundach znikają ikony

# --- Input Ring (wokół symbolu celu)
RING_RADIUS_FACTOR = 1        # promień ringu jako ułamek rozmiaru docelowego symbolu
RING_THICKNESS = 6               # grubość okręgu
RING_COLOR = (120, 200, 255, 120)
RING_ICON_SIZE_FACTOR = 0.44     # rozmiar ikon na ringu względem symbolu w centrum
RING_GLOW_COLOR = (255, 240, 120, 70)  # poświata pod poprawną ikoną
RING_GLOW_RADIUS = 24

# --- Ring layout (pozycje) ---
DEFAULT_RING_LAYOUT = {
    "TOP": "TRIANGLE",
    "RIGHT": "CIRCLE",
    "LEFT": "SQUARE",
    "BOTTOM": "CROSS",
}
RING_POSITIONS = ["TOP", "RIGHT", "LEFT", "BOTTOM"]

# --- Screens --- (rozmieszczenie elementów w ekranach MENU/OVER/SETTINGS)
MENU_TITLE_Y_FACTOR = 0.28        # pionowe położenie tytułu w MENU (proporcja wys.)
MENU_MODE_GAP = 20                # odstęp tytuł → wiersz „Mode:” (px; w kodzie skalowany)
MENU_HINT_GAP = 48                # odstęp do pierwszej podpowiedzi
MENU_HINT2_EXTRA_GAP = 12         # dodatkowy odstęp do drugiej podpowiedzi
OVER_TITLE_OFFSET_Y = -60         # przesunięcie tytułu „GAME OVER”
OVER_SCORE_GAP1 = -10             # przesunięcie pierwszej linii wyniku
OVER_SCORE_GAP2 = 26              # przesunięcie drugiej linii wyniku
OVER_INFO_GAP = 60                # odstęp do linii z instrukcją
SETTINGS_TITLE_Y_FACTOR = 0.10    # pionowe położenie tytułu „Settings”
SETTINGS_LIST_Y_START_FACTOR = 0.25  # start Y listy opcji
SETTINGS_ITEM_SPACING = 3         # odstęp między wierszami listy
SETTINGS_HELP_MARGIN_TOP = 18     # margines nad helpem na dole
SETTINGS_HELP_GAP = 6             # odstęp między wierszami helpu
SETTINGS_CENTER_GAP = 12          # odstęp między etykietą a wartością w wierszu

# --- Top Header & Score Capsule --- (górny HUD)
TOPBAR_HEIGHT_FACTOR = 0.1        # wysokość topbara (proporcja wys. okna)
TOPBAR_PAD_X_FACTOR = 0.045       # poziomy padding lewej/prawej sekcji
TOPBAR_UNDERLINE_THICKNESS = 4    # grubość linii pod topbarem
TOPBAR_UNDERLINE_COLOR = (90, 200, 255)  # kolor linii

SCORE_CAPSULE_WIDTH_FACTOR = 0.42 # szerokość kapsuły wyniku (proporcja szer.)
SCORE_CAPSULE_HEIGHT_FACTOR = 0.15# wysokość kapsuły (proporcja wys.)
SCORE_CAPSULE_BORDER_COLOR = (120, 200, 255, 220)  # obrys kapsuły
SCORE_CAPSULE_BG = (22, 26, 34, 170)               # tło kapsuły (z alpha)
SCORE_CAPSULE_RADIUS = 26          # promień rogów kapsuły
SCORE_CAPSULE_SHADOW = (0, 0, 0, 140)              # cień kapsuły
SCORE_CAPSULE_SHADOW_OFFSET = (3, 5)               # offset cienia
SCORE_CAPSULE_MIN_HEIGHT_BONUS = 15                # minimalny „dodatkowy” wzrost wysokości

# Typography (rozmiary bazowe; w kodzie są skalowane do okna)
FONT_PATH = "assets/font/Orbitron-VariableFont_wght.ttf"
FONT_SIZE_SMALL = 18
FONT_SIZE_MID = 24
FONT_SIZE_BIG = 60
FONT_SIZE_SETTINGS = 26
HUD_LABEL_FONT_SIZE = 22
HUD_VALUE_FONT_SIZE = 40
SCORE_LABEL_FONT_SIZE = 26
SCORE_VALUE_FONT_SIZE = 64
HUD_LABEL_COLOR = (180, 200, 230)   # kolor etykiet HUD
HUD_VALUE_COLOR = INK               # kolor wartości HUD
SCORE_LABEL_COLOR = ACCENT          # kolor napisu „SCORE”
SCORE_VALUE_COLOR = INK             # kolor liczby punktów

# --- Aspect --- (utrzymanie 9:16 w trybie okienkowym)
ASPECT_RATIO = (9, 16)             # docelowe proporcje (portret)
ASPECT_SNAP_MIN_SIZE = (360, 640)  # minimalny rozmiar okna po „snapie”
ASPECT_SNAP_TOLERANCE = 0.0        # tolerancja (0 = zawsze wymuszaj idealne 9:16)

# --- Audio ---
MUSIC_FADEOUT_MS = 800             # czas wyciszenia muzyki przy końcu gry

# --- Window --- (ustawienia okna)
WINDOWED_DEFAULT_SIZE = tuple(CFG.get("display", {}).get("windowed_size", (720, 1280)))  # domyślne 9:16
WINDOWED_FLAGS = pygame.RESIZABLE  # okno z paskiem tytułu i możliwością zmiany rozmiaru

# --- GPIO --- (przyciski sprzętowe – Raspberry Pi itd.)
GPIO_PULL_UP = True                # konfiguracja wejść (pull-up)
GPIO_BOUNCE_TIME = 0.05            # debounce w sekundach

# --- Keymap --- (mapowanie klawiszy na symbole gry)
KEYMAP: Dict[int, str] = {
    pygame.K_UP: "TRIANGLE",
    pygame.K_RIGHT: "CIRCLE",
    pygame.K_LEFT: "SQUARE",
    pygame.K_DOWN: "CROSS",
    pygame.K_w: "TRIANGLE",
    pygame.K_d: "CIRCLE",
    pygame.K_a: "SQUARE",
    pygame.K_s: "CROSS",
}


def init_gpio(iq: InputQueue):
    """Create gpiozero Button objects and bind them to the input queue.

    On Windows or if gpiozero is missing, returns an empty dict.
    """
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
    CIRCLE = auto()
    SQUARE = auto()
    CROSS = auto()


SYMS = [s.name for s in Symbol]


class Mode(Enum):
    SPEEDUP = auto()
    TIMED = auto()


class Scene(Enum):
    MENU = auto()
    GAME = auto()
    OVER = auto()
    SETTINGS = auto()
    INSTRUCTION = auto()

class RuleType(Enum):
    MAPPING = auto()   # „A ⇒ B” (baner NEW RULE)

class InputRouter:
    def __init__(self):
        self.keys_down=set(); self.lock=False; self.accept_after=0.0
        self.key_to_pos={...}
        self.layout = dict(DEFAULT_RING_LAYOUT)

    def recompute(self): ...
    def keydown(self, key, now)->Optional[str]: ...
    def keyup(self, key, now)->None: ...

@dataclass
class RuleSpec:
    type: RuleType
    banner_on_level_start: bool = False
    periodic_every_hits: int = 0  


@dataclass
class LevelCfg:
    id: int
    rules: List[RuleSpec] = field(default_factory=list)
    rotations_per_level: int = 0                            # ile rotacji w ramach poziomu (w tym jedna na starcie – patrz apply_level)
    memory_mode: bool = False                               # L5: po intro ring znika
    memory_intro_sec: float = 3.0                           # ile sekund podglądu układu ringu przy starcie memory (nadpisywalne)
    instruction: str = ""                                   # krótki tekst instrukcji
    instruction_sec: float = 5.0                            # ile sekund trwa ekran instrukcji
    score_color: Tuple[int,int,int] = SCORE_VALUE_COLOR

LEVELS: Dict[int, LevelCfg] = {
    1: LevelCfg(1,
        rules=[],
        instruction="Level 1 — Classic\nOdpowiadaj poprawnie.",
        score_color=(235,235,235)
    ),
    2: LevelCfg(2,
        rules=[RuleSpec(RuleType.MAPPING, banner_on_level_start=True, periodic_every_hits=RULE_EVERY_HITS)],
        instruction="Level 2 — New Rule\nZwracaj uwagę na baner.",
        score_color=(60,200,120)
    ),
    3: LevelCfg(3,
        rules=[],  # tylko rotacje, BEZ banera i BEZ mappingu
        rotations_per_level=3,
        instruction="Level 3 — Rotacje\nUkład ringu zmienia się w trakcie."
    ),
    4: LevelCfg(4,
        rules=[RuleSpec(RuleType.MAPPING, banner_on_level_start=True, periodic_every_hits=RULE_EVERY_HITS)],
        rotations_per_level=3,
        instruction="Level 4 — Mix\nReguły + rotacje."
    ),
    5: LevelCfg(5,
        rules=[],  # memory bez mappingu
        rotations_per_level=1,
        memory_mode=True, memory_intro_sec=3.0,
        instruction="Level 5 — Memory\nZapamiętaj układ, potem ikony znikną."
    ),
}


# ========= RULE MANAGER =========


class RuleManager:
    """Zarządza aktywnymi zasadami oraz aktualnym mappingiem A->B."""
    def __init__(self):
        self.active: dict[RuleType, RuleSpec] = {}
        self.current_mapping: Optional[Tuple[str, str]] = None
        self.mapping_every_hits = 0
        self.hits_since_roll = 0

    def install(self, specs: List[RuleSpec]) -> None:
        self.active.clear()
        self.current_mapping = None
        self.mapping_every_hits = 0
        self.hits_since_roll = 0
        for s in specs or []:
            self.active[s.type] = s
            if s.type is RuleType.MAPPING:
                self.mapping_every_hits = int(s.periodic_every_hits or 0)

    def on_correct(self) -> bool:
        """Zwraca True gdy trzeba odświeżyć mapping (co X trafień)."""
        if RuleType.MAPPING not in self.active or self.mapping_every_hits <= 0:
            return False
        self.hits_since_roll += 1
        if self.hits_since_roll >= self.mapping_every_hits:
            self.hits_since_roll = 0
            return True
        return False

    def roll_mapping(self, syms: List[str]) -> Tuple[str, str]:
        a = random.choice(syms)
        b = random.choice([s for s in syms if s != a])
        if self.current_mapping == (a, b):
            b = random.choice([s for s in syms if s not in (a, b)])
        self.current_mapping = (a, b)
        return self.current_mapping

    def apply(self, stimulus: str) -> str:
        if self.current_mapping and stimulus == self.current_mapping[0]:
            return self.current_mapping[1]
        return stimulus


# ========= BANNER MANAGER =========


class BannerManager:
    """Trzyma czas animacji banera: in -> hold -> out(dock)."""
    def __init__(self, in_sec: float, hold_sec: float, out_sec: float):
        self.in_sec = float(in_sec)
        self.hold_sec = float(hold_sec)
        self.out_sec = float(out_sec)
        self.total = self.in_sec + self.hold_sec + self.out_sec
        self.active_until = 0.0
        self.anim_start = 0.0
        self.from_pinned = False

    def is_active(self, now: float) -> bool:
        return now < self.active_until

    def start(self, now: float, from_pinned: bool = False) -> None:
        self.from_pinned = from_pinned
        self.anim_start = now
        self.active_until = now + self.total

    def phase(self, now: float) -> Tuple[str, float]:
        """Zwraca ('in'|'hold'|'out', progress 0..1)."""
        t = max(0.0, min(self.total, now - self.anim_start))
        if t <= self.in_sec:
            return "in", (t / max(1e-6, self.in_sec))
        if t <= self.in_sec + self.hold_sec:
            return "hold", 1.0
        return "out", ((t - self.in_sec - self.hold_sec) / max(1e-6, self.out_sec))


# ========= FX MANAGER =========
class EffectsManager:
    def __init__(self, now_fn, *, glitch_enabled: bool = True):
        import random as _rand
        self._rand = _rand
        self.now = now_fn
        # flags
        self.enabled = bool(glitch_enabled)

        # shake
        self.shake_start = 0.0
        self.shake_until = 0.0

        # glitch (post)
        self.glitch_active_until = 0.0
        self.glitch_start_time = 0.0
        self.glitch_mag = 1.0

        # text glitch
        self.text_glitch_active_until = 0.0
        self.next_text_glitch_at = self.now() + self._rand.uniform(TEXT_GLITCH_MIN_GAP, TEXT_GLITCH_MAX_GAP)

        # pulses
        self._pulses = { 'symbol': (0.0, 0.0), 'streak': (0.0, 0.0), 'banner': (0.0, 0.0) }

    # -------- cfg / reset --------
    def set_enabled(self, on: bool):
        self.enabled = bool(on)
        if not self.enabled:
            self.clear_transients()

    def clear_transients(self):
        self.shake_start = self.shake_until = 0.0
        self.glitch_active_until = self.glitch_start_time = 0.0
        self.glitch_mag = 1.0
        self.text_glitch_active_until = 0.0
        self._pulses = {k: (0.0, 0.0) for k in self._pulses}

    # -------- triggers --------
    def trigger_shake(self, duration: float = SHAKE_DURATION):
        now = self.now()
        self.shake_start = now
        self.shake_until = now + max(0.01, duration)

    def trigger_glitch(self, *, mag: float = 1.0, duration: float = GLITCH_DURATION):
        if not self.enabled:
            return
        now = self.now()
        self.glitch_mag = max(0.0, mag)
        self.glitch_active_until = now + max(0.01, duration)
        self.glitch_start_time = now
        self.trigger_shake()
        if self._rand.random() < 0.5:
            self.trigger_text_glitch()

    def trigger_text_glitch(self, duration: float = TEXT_GLITCH_DURATION):
        if not self.enabled:
            return
        now = self.now()
        self.text_glitch_active_until = now + max(0.05, duration)
        self.next_text_glitch_at = now + self._rand.uniform(TEXT_GLITCH_MIN_GAP, TEXT_GLITCH_MAX_GAP)

    def maybe_schedule_text_glitch(self):
        if not self.enabled:
            return
        now = self.now()
        if now >= self.next_text_glitch_at and not self.is_text_glitch_active():
            self.trigger_text_glitch()

    def is_text_glitch_active(self) -> bool:
        return self.enabled and (self.now() < self.text_glitch_active_until)

    def trigger_pulse(self, kind: str, duration: float = PULSE_DURATION):
        if kind not in self._pulses: return
        now = self.now()
        self._pulses[kind] = (now, now + max(1e-3, duration))

    def trigger_pulse_symbol(self): self.trigger_pulse('symbol')
    def trigger_pulse_streak(self): self.trigger_pulse('streak')
    def trigger_pulse_banner(self): self.trigger_pulse('banner')

    # -------- queries / math --------
    def _pulse_curve01(self, t: float) -> float:
        # 0→1→0 (sinus), podnosimy do [1, PULSE_MAX_SCALE]
        import math
        t = max(0.0, min(1.0, t))
        return 1.0 + (PULSE_MAX_SCALE - 1.0) * math.sin(math.pi * t)

    def pulse_scale(self, kind: str) -> float:
        start, until = self._pulses.get(kind, (0.0, 0.0))
        if start <= 0.0: return 1.0
        now = self.now()
        if now >= until: return 1.0
        dur = max(1e-6, until - start)
        t = (now - start) / dur
        return self._pulse_curve01(t)

    def shake_offset(self, screen_w: int) -> tuple[float, float]:
        import math
        now = self.now()
        if now >= self.shake_until: return (0.0, 0.0)
        sh_t = max(0.0, min(1.0, (now - self.shake_start) / SHAKE_DURATION))
        env = 1.0 - sh_t
        amp = screen_w * SHAKE_AMPLITUDE_FACT * env
        phase = 2.0 * math.pi * SHAKE_FREQ_HZ * (now - self.shake_start)
        dx = amp * math.sin(phase)
        dy = 0.5 * amp * math.cos(phase * 0.9)
        return (dx, dy)

    # -------- post-process glitch --------
    def apply_postprocess(self, frame: pygame.Surface, w: int, h: int) -> pygame.Surface:
        if not self.enabled: return frame
        now = self.now()
        if now >= self.glitch_active_until: return frame

        dur = max(1e-6, GLITCH_DURATION)
        t = 1.0 - (self.glitch_active_until - now) / dur
        vigor = (1 - abs(0.5 - t) * 2)
        strength = max(0.0, min(1.0, vigor * self.glitch_mag))

        # 1) pixelation
        pf = GLITCH_PIXEL_FACTOR_MAX * strength
        out = frame
        if pf > 0:
            sw, sh = max(1, int(w * (1 - pf))), max(1, int(h * (1 - pf)))
            small = pygame.transform.smoothscale(frame, (sw, sh))
            out = pygame.transform.scale(small, (w, h))

        # 2) RGB split
        ch_off = int(6 * strength) + self._rand.randint(0, 2)
        if ch_off:
            base = out.copy()
            for (mask, dx, dy) in (
                ((255, 0, 0, 255), ch_off, 0),
                ((0, 255, 0, 255), -ch_off, 0),
                ((0, 0, 255, 255), 0, ch_off),
            ):
                chan = base.copy()
                tint = pygame.Surface((w, h), pygame.SRCALPHA)
                tint.fill(mask)
                chan.blit(tint, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
                out.blit(chan, (dx, dy), special_flags=pygame.BLEND_ADD)

        # 3) displaced horizontal bands
        if self._rand.random() < 0.9:
            bands = self._rand.randint(2, 4)
            band_h = max(4, h // (bands * 8))
            for _ in range(bands):
                y = self._rand.randint(0, h - band_h)
                dx = self._rand.randint(-int(w * 0.03 * strength), int(w * 0.03 * strength))
                slice_rect = pygame.Rect(0, y, w, band_h)
                slice_surf = out.subsurface(slice_rect).copy()
                out.blit(slice_surf, (dx, y))

        # 4) colored blocks
        if self._rand.random() < 0.4 * strength:
            bw = self._rand.randint(w // 12, w // 4)
            bh = self._rand.randint(h // 24, h // 8)
            x = self._rand.randint(0, max(0, w - bw))
            y = self._rand.randint(0, max(0, h - bh))
            col = (
                self._rand.randint(180, 255),
                self._rand.randint(120, 255),
                self._rand.randint(120, 255),
                self._rand.randint(40, 100),
            )
            pygame.draw.rect(out, col, (x, y, bw, bh))
        return out


# ========= GAME =========

class Game:

    # ---- Inicjalizacja i podstawy cyklu życia ----

    def __init__(self, screen: pygame.Surface, mode: Mode = Mode.SPEEDUP):
        self.screen = screen
        self.cfg = CFG
        self.images = IMAGES
        self.mode: Mode = mode
        self.scene: Scene = Scene.MENU

        self.w, self.h = self.screen.get_size()
        self.clock = pygame.time.Clock()

        # --- key delay / debouncing for keyboard ---
        self.keys_down: set[int] = set()
        self.lock_until_all_released = False
        self.accept_after = 0.0

        # --- fonts ---
        self.font = pygame.font.Font(FONT_PATH, FONT_SIZE_SMALL)
        self.big = pygame.font.Font(FONT_PATH, FONT_SIZE_BIG)
        self.mid = pygame.font.Font(FONT_PATH, FONT_SIZE_MID)
        self.timer_font = pygame.font.Font(FONT_PATH, TIMER_FONT_SIZE)
        self.hud_label_font = pygame.font.Font(FONT_PATH, HUD_LABEL_FONT_SIZE)
        self.hud_value_font = pygame.font.Font(FONT_PATH, HUD_VALUE_FONT_SIZE)
        self.score_label_font = pygame.font.Font(FONT_PATH, SCORE_LABEL_FONT_SIZE)
        self.score_value_font = pygame.font.Font(FONT_PATH, SCORE_VALUE_FONT_SIZE)
        self.settings_font = pygame.font.Font(FONT_PATH, FONT_SIZE_SETTINGS)

        # background
        self.bg_img_raw = self._load_background()
        self.bg_img: Optional[pygame.Surface] = None

        # layout & framebuffer
        self._recompute_layout()
        self._rescale_background()
        self.fb = pygame.Surface((self.w, self.h), pygame.SRCALPHA)

        # fonts for rule banner stages (center vs pinned)
        self.rule_font_center: Optional[pygame.font.Font] = None
        self.rule_font_pinned: Optional[pygame.font.Font] = None
        self._build_rule_fonts()
        self.ui_scale = 1.0
        self._rebuild_fonts() 

        # gameplay state
        self.level = 1
        self.hits_in_level = 0
        self.level_goal = LEVEL_GOAL_PER_LEVEL
        self.levels_active = LEVELS_ACTIVE_FOR_NOW

        self.score = 0
        self.lives = MAX_LIVES
        self.streak = 0

        self.target: Optional[str] = None
        self.target_deadline: Optional[float] = None
        self.target_time = TARGET_TIME_INITIAL

        self.pause_start = 0.0
        self.pause_until = 0.0
        self.symbol_spawn_time = 0.0
        self.time_left = TIMED_DURATION
        self._last_tick = 0.0
        self.highscore = int(CFG.get("highscore", 0))

        # --- level cfg / ring state ---
        self.level_cfg: LevelCfg = LEVELS[1]

        # --- rule / banner manager ---
        self.rules = RuleManager()
        self.banner = BannerManager(RULE_BANNER_IN_SEC, RULE_BANNER_HOLD_SEC, RULE_BANNER_TO_TOP_SEC)

        # ring: pos -> symbol (dynamiczny)
        self.ring_layout = dict(DEFAULT_RING_LAYOUT)

        # memory (L5)
        self.memory_show_icons = True
        self.memory_intro_until = 0.0   # (stare – nie użyjemy już do ukrywania)
        self.memory_hide_deadline = 0.0 # nowy: kiedy najpóźniej ukryć ikony (czasowo)
        self.memory_moves_count = 0     # nowy: ile ruchów wykonano zanim znikną

        # klawisze mapują do POZYCJI; symbole wynikają z ring_layout
        self.key_to_pos = {
            pygame.K_UP: "TOP", pygame.K_RIGHT: "RIGHT", pygame.K_LEFT: "LEFT", pygame.K_DOWN: "BOTTOM",
            pygame.K_w: "TOP",  pygame.K_d: "RIGHT",     pygame.K_a: "LEFT",   pygame.K_s: "BOTTOM",
        }
        self.keymap_current: Dict[int, str] = {}
        self._recompute_keymap()

        # rotacje w obrębie poziomu
        self.rotation_breaks: set[int] = set()  # np. {5, 10} dla 15 hitów
        self.did_start_rotation = False         # pierwsza rotacja „na start poziomu” wykonana?

        # instrukcja między levelami
        self.instruction_until = 0.0
        self.instruction_text = ""
        self.allow_skip_instruction = True

        # memory (L5)
        self.memory_show_icons = True          # czy rysować ikony na ringu
        self.memory_intro_until = 0.0          # kiedy zakończyć podgląd układu

        # settings buffer (Settings scene)
        self.settings_idx = 0
        self.settings = {
            "target_time_initial": float(CFG["speedup"]["target_time_initial"]),
            "target_time_step": float(CFG["speedup"]["target_time_step"]),
            "target_time_min": float(CFG["speedup"]["target_time_min"]),
            "lives": int(CFG["lives"]),
            "glitch_enabled": bool(CFG.get("effects", {}).get("glitch_enabled", True)),
            "volume": float(CFG["audio"]["volume"]),
            "fullscreen": bool(CFG["display"]["fullscreen"]),
            "timed_rule_bonus": float(CFG["timed"].get("rule_bonus", 5.0)),
            # expose banner fonts in settings so they can be tweaked live
            "rule_font_center": int(CFG["rules"].get("banner_font_center", 64)),
            "rule_font_pinned": int(CFG["rules"].get("banner_font_pinned", 40)),
        }

        # effects
        self.fx = EffectsManager(self.now, glitch_enabled=self.settings.get("glitch_enabled", True))

        # music
        self.music_ok = False
        self._ensure_music()
        self.last_window_size = self.screen.get_size()

    def start_game(self) -> None:
        self.reset_game_state()
        self._ensure_music()
        if self.music_ok:
            pygame.mixer.music.play(-1)

    def end_game(self) -> None:
        self.scene = Scene.OVER
        if self.score > self.highscore:
            self.highscore = self.score
            CFG["highscore"] = int(self.highscore)
            save_config({"highscore": CFG["highscore"]})
        if self.music_ok:
            pygame.mixer.music.fadeout(MUSIC_FADEOUT_MS)

    # ---- Czas i proste utilsy ----

    def now(self) -> float:
        return time.time()
  
    def px(self, v: float) -> int:
        return max(1, int(round(v * getattr(self, "ui_scale", 1.0))))

    @staticmethod
    def _ease_out_cubic(t: float) -> float:
        t = max(0.0, min(1.0, t))
        return 1 - (1 - t) ** 3

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

    def lives_enabled(self) -> bool:
        return int(self.settings.get("lives", MAX_LIVES)) > 0

# ---- Zasoby, layout, UI scale, fonty, tło ----

    def _ensure_framebuffer(self) -> None:
        self.fb = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
    
    def _compute_ui_scale(self) -> float:
        ref_w, ref_h = 720, 1280
        sx = self.w / ref_w
        sy = self.h / ref_h
        s = min(sx, sy)
        return max(0.6, min(2.2, s))  # clamp

    def _rebuild_fonts(self) -> None:
        self.ui_scale = self._compute_ui_scale()

        def S(px: int) -> int:
            return max(8, int(round(px * self.ui_scale)))

        # główne fonty UI
        self.font         = pygame.font.Font(FONT_PATH, S(FONT_SIZE_SMALL))
        self.mid          = pygame.font.Font(FONT_PATH, S(FONT_SIZE_MID))
        self.big          = pygame.font.Font(FONT_PATH, S(FONT_SIZE_BIG))
        self.timer_font   = pygame.font.Font(FONT_PATH, S(TIMER_FONT_SIZE))
        self.hud_label_font   = pygame.font.Font(FONT_PATH, S(HUD_LABEL_FONT_SIZE))
        self.hud_value_font   = pygame.font.Font(FONT_PATH, S(HUD_VALUE_FONT_SIZE))
        self.score_label_font = pygame.font.Font(FONT_PATH, S(SCORE_LABEL_FONT_SIZE))
        self.score_value_font = pygame.font.Font(FONT_PATH, S(SCORE_VALUE_FONT_SIZE))
        self.settings_font    = pygame.font.Font(FONT_PATH, S(FONT_SIZE_SETTINGS))

        # fonty banera reguły – bazują na wartościach z configu, ale też skaluje je UI
        c = S(int(CFG["rules"].get("banner_font_center", 64)))
        p = S(int(CFG["rules"].get("banner_font_pinned", 40)))
        self.rule_font_center = pygame.font.Font(FONT_PATH, max(8, c))
        self.rule_font_pinned = pygame.font.Font(FONT_PATH, max(8, p))

    def _build_rule_fonts(self) -> None:
        c = int(CFG["rules"].get("banner_font_center", 64))
        p = int(CFG["rules"].get("banner_font_pinned", 40))
        self.rule_font_center = pygame.font.Font(FONT_PATH, c)
        self.rule_font_pinned = pygame.font.Font(FONT_PATH, p)

    def _load_background(self) -> Optional[pygame.Surface]:
        path = CFG.get("images", {}).get("background") if isinstance(CFG.get("images"), dict) else None
        if not path or not os.path.exists(path):
            return None
        return IMAGES.load(path, allow_alpha=True)

    def _rescale_background(self) -> None:
        raw = getattr(self, "bg_img_raw", None)
        if not raw:
            self.bg_img = None
            return
        rw, rh = raw.get_size()
        sw, sh = self.w, self.h
        scale = max(sw / rw, sh / rh)  # cover
        new_size = (int(rw * scale), int(rh * scale))
        img = pygame.transform.smoothscale(raw, new_size)
        x = (img.get_width() - sw) // 2
        y = (img.get_height() - sh) // 2
        self.bg_img = img.subsurface(pygame.Rect(x, y, sw, sh)).copy()

    def _recompute_layout(self) -> None:
        self.w, self.h = self.screen.get_size()

        # --- Pads layout (kept for potential future use) ---
        pad_w = (self.w * (1 - 2 * PADDING - GAP)) / 2
        pad_h = (self.h * (1 - 2 * PADDING - GAP)) / 2
        x1 = self.w * PADDING
        x2 = x1 + pad_w + self.w * GAP
        y1 = self.h * PADDING
        y2 = y1 + pad_h + self.h * GAP
        self.pads = {
            "TRIANGLE": pygame.Rect(x1, y1, pad_w, pad_h),
            "CIRCLE": pygame.Rect(x2, y1, pad_w, pad_h),
            "SQUARE": pygame.Rect(x1, y2, pad_w, pad_h),
            "CROSS": pygame.Rect(x2, y2, pad_w, pad_h),
        }

        # --- Top header and score capsule geometry ---
        self.topbar_h = int(self.h * TOPBAR_HEIGHT_FACTOR)
        self.topbar_rect = pygame.Rect(0, 0, self.w, self.topbar_h)

        cap_h = int(self.h * SCORE_CAPSULE_HEIGHT_FACTOR)
        if cap_h <= self.topbar_h:
            cap_h = self.topbar_h + SCORE_CAPSULE_MIN_HEIGHT_BONUS

        cap_w = int(self.w * SCORE_CAPSULE_WIDTH_FACTOR)
        self.score_capsule_rect = pygame.Rect(0, 0, cap_w, cap_h)

        desired_cy = self.topbar_rect.top + self.topbar_h // 2
        min_cy = cap_h // 2 + 4
        cy = max(min_cy, desired_cy)
        self.score_capsule_rect.center = (self.w // 2, cy)

        self._rescale_background()
        self._ensure_framebuffer()
        self._rebuild_fonts() 

    def _ensure_music(self) -> None:
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

# ---- Okno/tryb wyświetlania & rozmiar ----

    def _set_display_mode(self, fullscreen: bool) -> None:
        if fullscreen:
            # systemowy fullscreen (bez zabawy z rozmiarem pulpitu)
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            # klasyczne okno z paskiem tytułu
            w, h = getattr(self, "last_windowed_size", WINDOWED_DEFAULT_SIZE)
            w, h = self._snap_to_aspect(w, h)
            self.screen = pygame.display.set_mode((w, h), WINDOWED_FLAGS)
            self.last_windowed_size = self.screen.get_size()
            _persist_windowed_size(*self.last_windowed_size)

        self.last_window_size = self.screen.get_size()
        self._recompute_layout()
        pygame.display.set_caption("Remap")

    def _snap_to_aspect(self, width: int, height: int) -> Tuple[int, int]:
        target_w, target_h = ASPECT_RATIO
        ratio = target_w / target_h
        last_w, last_h = getattr(self, "last_window_size", (width, height))
        if ASPECT_SNAP_TOLERANCE > 0:
            r = width / max(1, height)
            if abs(r - ratio) <= ASPECT_SNAP_TOLERANCE * ratio:
                return max(ASPECT_SNAP_MIN_SIZE[0], width), max(ASPECT_SNAP_MIN_SIZE[1], height)
        dw = abs(width - last_w)
        dh = abs(height - last_h)
        if dw >= dh:
            height = int(round(width / ratio))
        else:
            width = int(round(height * ratio))
        width = max(ASPECT_SNAP_MIN_SIZE[0], width)
        height = max(ASPECT_SNAP_MIN_SIZE[1], height)
        return width, height

    def apply_fullscreen_now(self) -> None:
        want_full = bool(self.settings.get("fullscreen", True))
        if want_full:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            w, h = getattr(self, "last_window_size", None) or tuple(
                CFG.get("display", {}).get("windowed_size", WINDOWED_DEFAULT_SIZE)
            )
            self.screen = pygame.display.set_mode((w, h), WINDOWED_FLAGS)
            _persist_windowed_size(*self.screen.get_size())
        self.last_window_size = self.screen.get_size()
        self._recompute_layout()

    def handle_resize(self, width: int, height: int) -> None:
        if bool(CFG.get("display", {}).get("fullscreen", True)):
            return
        width, height = self._snap_to_aspect(width, height)
        self.screen = pygame.display.set_mode((width, height), WINDOWED_FLAGS)
        self.last_window_size = (width, height)
        _persist_windowed_size(width, height)
        self._recompute_layout()

# ---- Klawisze i mapowania wejść ----

    def _recompute_keymap(self) -> None:
        self.keymap_current = {k: self.ring_layout[pos] for k, pos in self.key_to_pos.items()}

# ---- Ustawienia ----

    def settings_items(self):
        return [
            ("Initial time", f"{self.settings['target_time_initial']:.2f}s", "target_time_initial"),
            ("Time step", f"{self.settings['target_time_step']:+.2f}s/hit", "target_time_step"),
            ("Minimum time", f"{self.settings['target_time_min']:.2f}s", "target_time_min"),
            ("Lives", f"{int(self.settings['lives'])}", "lives"),
            ("Volume", f"{self.settings['volume']:.2f}", "volume"),
            ("Fullscreen", "ON" if self.settings['fullscreen'] else "OFF", "fullscreen"),
            ("Glitch", "ON" if self.settings.get('glitch_enabled', True) else "OFF", "glitch_enabled"),
            ("High score", f"{self.highscore}", None),
            ("Rule bonus", f"{self.settings['timed_rule_bonus']:.1f}s", "timed_rule_bonus"),
            ("Banner font (center)", f"{self.settings['rule_font_center']}", "rule_font_center"),
            ("Banner font (pinned)", f"{self.settings['rule_font_pinned']}", "rule_font_pinned"),
        ]

    def settings_move(self, delta: int) -> None:
        items = self.settings_items()
        n, idx = len(items), self.settings_idx
        for _ in range(n):
            idx = (idx + delta) % n
            if items[idx][2] is not None:
                self.settings_idx = idx
                return
        self.settings_idx = 0

    def toggle_settings(self) -> None:
        if self.scene is Scene.SETTINGS:
            self.settings_cancel()
        elif self.scene is Scene.MENU:
            self.open_settings()

    def _settings_clamp(self) -> None:
        s = self.settings
        s["target_time_initial"] = max(0.2, min(10.0, float(s.get("target_time_initial", 3))))
        s["target_time_min"] = max(0.1, min(float(s["target_time_initial"]), float(s.get("target_time_min", 0.45))))
        s["target_time_step"] = max(-1.0, min(1.0, float(s.get("target_time_step", -0.03))))
        s["lives"] = max(0, min(9, int(s.get("lives", 3))))
        s["volume"] = max(0.0, min(1.0, float(s.get("volume", 0.5))))
        s["timed_rule_bonus"] = max(0.0, min(30.0, float(s.get("timed_rule_bonus", 5.0))))
        s["rule_font_center"] = max(8, min(200, int(s.get("rule_font_center", 64))))
        s["rule_font_pinned"] = max(8, min(200, int(s.get("rule_font_pinned", 40))))

    def settings_adjust(self, delta: int) -> None:
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
            self.fx.set_enabled(self.settings["glitch_enabled"])
            return

        step = {
            "target_time_initial": 0.1,
            "target_time_step": 0.01,
            "target_time_min": 0.05,
            "lives": 1,
            "volume": 0.05,
            "timed_rule_bonus": 0.5,
            "rule_font_center": 2,
            "rule_font_pinned": 2,
        }.get(key, 0.0)
        if step == 0.0:
            return

        cur = self.settings[key]
        self.settings[key] = (cur + (step * delta)) if isinstance(cur, float) else (cur + delta)
        self._settings_clamp()
        if key == "volume" and self.music_ok:
            pygame.mixer.music.set_volume(float(self.settings["volume"]))

    def settings_reset_highscore(self) -> None:
        self.highscore = 0
        CFG["highscore"] = 0
        save_config({"highscore": 0})

    def open_settings(self) -> None:
        # Refresh snapshot from CFG to ensure external edits are reflected.
        self.settings.update({
            "target_time_initial": float(CFG["speedup"]["target_time_initial"]),
            "target_time_step": float(CFG["speedup"]["target_time_step"]),
            "target_time_min": float(CFG["speedup"]["target_time_min"]),
            "lives": int(CFG["lives"]),
            "glitch_enabled": bool(CFG.get("effects", {}).get("glitch_enabled", True)),
            "volume": float(CFG["audio"]["volume"]),
            "fullscreen": bool(CFG["display"]["fullscreen"]),
            "timed_rule_bonus": float(CFG["timed"].get("rule_bonus", 5.0)),
            "rule_font_center": int(CFG["rules"].get("banner_font_center", 64)),
            "rule_font_pinned": int(CFG["rules"].get("banner_font_pinned", 40)),
        })
        self.settings_idx = 0
        self.settings_move(0)
        self.fx.trigger_glitch(mag=1.0)
        self.scene = Scene.SETTINGS

    def settings_save(self) -> None:
        self._settings_clamp()
        s = self.settings
        CFG["speedup"].update(
            {
                "target_time_initial": float(s["target_time_initial"]),
                "target_time_step": float(s["target_time_step"]),
                "target_time_min": float(s["target_time_min"]),
            }
        )
        CFG["lives"] = int(s["lives"])
        CFG["effects"] = CFG.get("effects", {})
        CFG["effects"]["glitch_enabled"] = bool(s["glitch_enabled"])
        CFG["audio"]["volume"] = float(s["volume"])
        CFG["display"]["fullscreen"] = bool(s["fullscreen"])
        CFG["timed"]["rule_bonus"] = float(s["timed_rule_bonus"])
        CFG["rules"]["banner_font_center"] = int(s["rule_font_center"]) 
        CFG["rules"]["banner_font_pinned"] = int(s["rule_font_pinned"]) 

        save_config(
            {
                "speedup": CFG["speedup"],
                "lives": CFG["lives"],
                "effects": {"glitch_enabled": CFG["effects"]["glitch_enabled"]},
                "audio": {"volume": CFG["audio"]["volume"]},
                "display": {
                    "fullscreen": CFG["display"]["fullscreen"],
                    "fps": CFG["display"]["fps"],
                    "windowed_size": CFG["display"].get("windowed_size", list(WINDOWED_DEFAULT_SIZE)),
                },
                "timed": {"rule_bonus": CFG["timed"]["rule_bonus"], "duration": CFG["timed"].get("duration", TIMED_DURATION)},
                "rules": {
                    "every_hits": CFG["rules"].get("every_hits", RULE_EVERY_HITS),
                    "banner_sec": CFG["rules"].get("banner_sec", RULE_BANNER_SEC),
                    "banner_font_center": CFG["rules"]["banner_font_center"],
                    "banner_font_pinned": CFG["rules"]["banner_font_pinned"],
                },
                "highscore": CFG.get("highscore", 0),
            }
        )
        if self.music_ok:
            pygame.mixer.music.set_volume(float(CFG["audio"]["volume"]))
        self._set_display_mode(bool(CFG["display"]["fullscreen"]))
        self._build_rule_fonts()
        self.fx.trigger_glitch(mag=1.0)
        self.scene = Scene.MENU

    def settings_cancel(self) -> None:
        self.fx.trigger_glitch(mag=1.0)
        self.scene = Scene.MENU

# ---- # ---- Okno/tryb wyświetlania & rozmiar ---- ----

    def reset_game_state(self) -> None:
        self.level = 1
        self.hits_in_level = 0
        self.level_goal = LEVEL_GOAL_PER_LEVEL
        self.score = 0
        self.streak = 0
        self.lives = int(self.settings.get("lives", MAX_LIVES))
        self.rules.install([])
        self.target = None
        self.target_deadline = None
        self.target_time = float(self.settings.get("target_time_initial", TARGET_TIME_INITIAL))
        self.symbol_spawn_time = 0.0
        self.pause_start = 0.0
        self.pause_until = 0.0
        self.time_left = TIMED_DURATION
        self._last_tick = self.now()

        # ring / remap reset
        self.ring_layout = dict(DEFAULT_RING_LAYOUT)
        self._recompute_keymap()

        # level 1 config + instrukcja
        self.apply_level(1)

    def apply_level(self, lvl: int) -> None:
        self.level_cfg = LEVELS.get(lvl, LEVELS[max(LEVELS.keys())])

        # wyczyść reguły poprzedniego levelu (instalacja konkretnych nastąpi po INSTRUCTION)
        self.rules.install([])

        # rotacje / memory / instrukcja — jak u Ciebie
        self._plan_rotations_for_level()
        self.memory_show_icons = True
        self.memory_intro_until = 0.0
        self.instruction_text = self.level_cfg.instruction or f"LEVEL {lvl}"
        self.instruction_until = self.now() + float(self.level_cfg.instruction_sec or 0.0)
        self.scene = Scene.INSTRUCTION

        if self.level_cfg.rotations_per_level > 0:
            self._rotate_ring_random()
            self.did_start_rotation = True

        if self.level_cfg.memory_mode:
            self.memory_show_icons = True
            self.memory_intro_until = 0.0

    def _plan_rotations_for_level(self) -> None:
        self.rotation_breaks = set()
        self.did_start_rotation = False
        N = self.level_cfg.rotations_per_level
        if N > 0:
            seg = max(1, self.level_goal // N)   # np. 15//3 = 5 → progi po 5 i 10 (startowa rotacja robiona osobno)
            for i in range(1, N):                # „w trakcie”
                self.rotation_breaks.add(i * seg)

    def _rotate_ring_random(self) -> None:
        current = [self.ring_layout[p] for p in RING_POSITIONS]
        symbols = list(SYMS)
        while True:
            random.shuffle(symbols)
            if symbols != current:
                break
        for p, s in zip(RING_POSITIONS, symbols):
            self.ring_layout[p] = s
        self._recompute_keymap()
        self.fx.trigger_glitch(mag=0.6)  # czytelny efekt zmiany

    def level_up(self) -> None:
        if self.level < self.levels_active:
            self.level += 1
            self.hits_in_level = 0
            self.apply_level(self.level)  # mapping na starcie odpali się po INSTRUCTION

    def level_value_color(self) -> Tuple[int, int, int]:
        return getattr(self.level_cfg, "score_color", LEVEL_COLORS.get(self.level, SCORE_VALUE_COLOR))

    def new_target(self) -> None:
        prev = self.target
        choices = [s for s in SYMS if s != prev] if prev else SYMS
        self.target = random.choice(choices)
        self.target_deadline = self.now() + self.target_time if self.mode is Mode.SPEEDUP else None
        self.symbol_spawn_time = self.now()

    def _start_mapping_banner(self, from_pinned: bool = False) -> None:
        now = self.now()
        self.banner.start(now, from_pinned=from_pinned)
        # pauza wejścia i czasu reakcji
        self.pause_start = now
        self.pause_until = self.banner.active_until
        # w TIMED dodajemy bonus tylko gdy baner rzeczywiście się pokazuje
        if self.mode is Mode.TIMED:
            self.time_left += ADDITIONAL_RULE_TIME

    def _enter_gameplay_after_instruction(self) -> None:
        self.scene = Scene.GAME
        if self.mode is Mode.TIMED:
            self._last_tick = self.now()

        # memory – okno podglądu po wejściu do GAME
        if self.level_cfg.memory_mode:
            self.memory_show_icons = True
            self.memory_moves_count = 0
            self.memory_hide_deadline = self.now() + float(MEMORY_HIDE_AFTER_SEC)

        # 1) Zainstaluj reguły DLA TEGO levelu (czyści poprzednie)
        self.rules.install(self.level_cfg.rules)

        # 2) Jeśli level wymaga banera mappingu na starcie – wylosuj TERAZ (po instrukcji) i uruchom baner
        mapping_spec = next((s for s in (self.level_cfg.rules or [])
                            if s.type is RuleType.MAPPING and s.banner_on_level_start), None)
        if mapping_spec:
            self.rules.roll_mapping(SYMS)
            self._start_mapping_banner(from_pinned=False)

        # 3) Nowy target na start rozgrywki
        self.new_target()

# ---- Pętla gry i wejścia (flow rozgrywki) ----

    def handle_event(self, event: pygame.event.Event, iq: InputQueue):
        if event.type == pygame.VIDEORESIZE:
            self.handle_resize(event.w, event.h)
            return

        if event.type == pygame.KEYDOWN:
            # --- global shortcuts ---
            if event.key in (pygame.K_ESCAPE, pygame.K_q):
                pygame.quit(); sys.exit(0)

            if event.key == pygame.K_o and self.scene in (Scene.MENU, Scene.SETTINGS):
                self.toggle_settings()
                return

            # --- scene-specific ---
            if self.scene is Scene.MENU:
                if event.key == pygame.K_RETURN:
                    self.start_game(); return
                if event.key == pygame.K_m:
                    self.mode = (Mode.TIMED if self.mode is Mode.SPEEDUP else Mode.SPEEDUP); return

            elif self.scene is Scene.OVER:
                if event.key == pygame.K_SPACE:
                    self.start_game(); return

            elif self.scene is Scene.SETTINGS:
                if event.key == pygame.K_ESCAPE:
                    self.settings_cancel(); return
                if event.key == pygame.K_RETURN:
                    self.settings_save(); return
                if event.key == pygame.K_UP:
                    self.settings_move(-1); return
                if event.key == pygame.K_DOWN:
                    self.settings_move(+1); return
                if event.key == pygame.K_LEFT:
                    self.settings_adjust(-1); return
                if event.key == pygame.K_RIGHT:
                    self.settings_adjust(+1); return
                if event.key == pygame.K_r:
                    self.settings_reset_highscore(); return
            
            elif self.scene is Scene.INSTRUCTION:
                # ENTER lub dowolny klawisz akcji = skip
                if event.key in (pygame.K_RETURN, pygame.K_SPACE) or event.key in self.key_to_pos:
                    self.instruction_until = 0.0  # natychmiast przejdź do gry
                    return

            # mark key as down for debouncing
            self.keys_down.add(event.key)

            # translate to a game symbol if present in keymap
            name = self.keymap_current.get(event.key)
            if name:
                # basic key lock to prevent accidental multi-presses
                if self.lock_until_all_released or self.now() < getattr(self, "accept_after", 0.0):
                    return
                iq.push(name)

        elif event.type == pygame.KEYUP:
            self.keys_down.discard(event.key)
            if self.lock_until_all_released and not self.keys_down and self.now() >= getattr(self, "accept_after", 0.0):
                self.lock_until_all_released = False

    def handle_input_symbol(self, name: str) -> None:
        if self.scene is not Scene.GAME or not self.target:
            return
        
        # MEMORY: zlicz ruchy do ukrycia (liczy KAŻDY ruch w scenie GAME)
        if self.level_cfg.memory_mode and self.memory_show_icons:
            self.memory_moves_count += 1
            if self.memory_moves_count >= MEMORY_HIDE_AFTER_MOVES:
                self.memory_show_icons = False

        required = self.rules.apply(self.target)
        if name == required:
            # Dobra odpowiedz

            self.score += 1
            self.streak += 1
            if self.streak > 0 and self.streak % 10 == 0:
                self.fx.trigger_pulse_streak()
            self.hits_in_level += 1

            if self.mode is Mode.TIMED:
                self.time_left += 1.0
            if self.mode is Mode.SPEEDUP:
                step = float(self.settings.get("target_time_step", TARGET_TIME_STEP))
                tmin = float(self.settings.get("target_time_min", TARGET_TIME_MIN))
                self.target_time = max(tmin, self.target_time + step)

            # cykliczne odświeżanie mappingu (jeśli aktywne)
            if self.rules.on_correct():
                self.rules.roll_mapping(SYMS)
                self._start_mapping_banner(from_pinned=True)

            # rotacje w tym levelu
            if self.level_cfg.rotations_per_level > 0 and self.hits_in_level in self.rotation_breaks:
                self._rotate_ring_random()

            if self.hits_in_level >= self.level_goal:
                self.level_up()

            self.new_target()
            self.lock_until_all_released = True
            self.accept_after = self.now() + 0.12

        else:

            #Zla odpowiedz


            if self.rules.current_mapping and self.target == self.rules.current_mapping[0]:
                self.fx.trigger_pulse_banner()
            self.streak = 0
            self.fx.trigger_shake()
            self.fx.trigger_glitch()
            if self.mode is Mode.TIMED:
                self.time_left -= 1.0
                if self.time_left <= 0.0:
                    self.time_left = 0.0
                    self.end_game()
            if self.mode is Mode.SPEEDUP and self.lives_enabled():
                self.lives -= 1
                if self.lives <= 0:
                    self.end_game()

    def update(self, iq: InputQueue) -> None:
        now = self.now()
        self.fx.maybe_schedule_text_glitch()

        # debounce
        if self.lock_until_all_released and not self.keys_down and now >= self.accept_after:
            self.lock_until_all_released = False

        # INSTRUKCJA: czekamy do końca timera albo na skip
        if self.scene is Scene.INSTRUCTION:
            _ = iq.pop_all()
            if now >= self.instruction_until:
                self._enter_gameplay_after_instruction()
            return

        if self.scene is not Scene.GAME:
            _ = iq.pop_all()
            return
        
        if self.banner.is_active(now):
            _ = iq.pop_all()
            # nie licz upływu czasu w TIMED, „zamrażamy” też timeout targetu
            self._last_tick = now
            return

        # „odkorkuj” po pauzie
        if self.pause_until and now >= self.pause_until:
            paused = max(0.0, self.pause_until - (self.pause_start or self.pause_until))
            self.pause_start = 0.0
            self.pause_until = 0.0
            if self.target_deadline is not None:
                self.target_deadline += paused
            self._last_tick = now

        # TIMED: upływ czasu
        if self.mode is Mode.TIMED:
            dt = max(0.0, now - (self._last_tick or now))
            self.time_left -= dt
            self._last_tick = now
            if self.time_left <= 0.0:
                self.time_left = 0.0
                self.end_game()
                return

        # SPEEDUP: timeout targetu
        if (self.mode is Mode.SPEEDUP and self.target is not None and
            self.target_deadline is not None and now > self.target_deadline):
            if self.lives_enabled():
                self.lives -= 1
            self.streak = 0
            self.fx.trigger_glitch()
            if self.lives <= 0:
                self.end_game()
                return
            self.new_target()

        # MEMORY: ukryj ikony po czasie (jeśli jeszcze są widoczne)
        if self.level_cfg.memory_mode and self.memory_show_icons:
            if now >= self.memory_hide_deadline:
                self.memory_show_icons = False

        # wejścia gracza
        for n in iq.pop_all():
            self.handle_input_symbol(n)

# ---- Rysowanie ----

    def _draw_round_rect(
        self,
        surf: pygame.Surface,
        rect: pygame.Rect,
        fill,
        border=None,
        border_w=1,
        radius=12,
    ) -> None:
        rr = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(rr, fill, rr.get_rect(), border_radius=radius)
        if border is not None and border_w > 0:
            pygame.draw.rect(rr, border, rr.get_rect(), width=border_w, border_radius=radius)
        surf.blit(rr, rect.topleft)
        
    def _shadow_text(self, surf: pygame.Surface) -> pygame.Surface:
        sh = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        sh.blit(surf, (0, 0))
        tint = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        tint.fill((0, 0, 0, 255))
        sh.blit(tint, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        return sh

    def draw_text(self, font, text, pos, color=INK, shadow=True):
        render_text = self._glitch_text(text) if self.fx.is_text_glitch_active() else text
        if shadow:
            shadow_surf = font.render(render_text, True, (0, 0, 0))
            self.screen.blit(shadow_surf, (pos[0] + 2, pos[1] + 2))
        txt_surf = font.render(render_text, True, color)
        self.screen.blit(txt_surf, pos)

    def draw_chip(
        self,
        text: str,
        x: int,
        y: int,
        pad: int = 10,
        radius: int = 10,
        bg=(20, 22, 30, 160),
        border=(120, 200, 255, 220),
        text_color=INK,
        *,
        font: Optional[pygame.font.Font] = None,
    ) -> pygame.Rect:
        fnt = font or self.font
        t_surf = fnt.render(text, True, text_color)
        w, h = t_surf.get_width() + pad * 2, t_surf.get_height() + pad * 2

        chip = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(chip, bg, chip.get_rect(), border_radius=radius)
        pygame.draw.rect(chip, border, chip.get_rect(), width=1, border_radius=radius)

        shadow = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 120), shadow.get_rect(), border_radius=radius + 2)
        self.screen.blit(shadow, (x + 3, y + 4))

        chip.blit(t_surf, (pad, pad))
        self.screen.blit(chip, (x, y))
        return pygame.Rect(x, y, w, h)

    def draw_arrow(self, surface: pygame.Surface, rect: pygame.Rect, color=RULE_ARROW_COLOR, width=RULE_ARROW_W) -> None:
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
        # vector fallback
        ax1 = rect.left + width
        ax2 = rect.right - width * 1.5
        ay = rect.centery
        pygame.draw.line(surface, color, (ax1, ay), (ax2, ay), width)
        head_w = min(rect.width * 0.32, rect.height * 0.9)
        half_h = min(rect.height * 0.45, rect.width * 0.28)
        p1 = (ax2, ay)
        p2 = (ax2 - head_w, ay - half_h)
        p3 = (ax2 - head_w, ay + half_h)
        pygame.draw.polygon(surface, color, (p1, p2, p3), width)

    def draw_symbol(self, surface: pygame.Surface, name: str, rect: pygame.Rect) -> None:
        path = self.cfg["images"].get(f"symbol_{name.lower()}")
        img = self.images.load(path)
        if not img:
            # vector fallback
            color = SYMBOL_COLORS.get(name, INK)
            thickness = SYMBOL_DRAW_THICKNESS
            cx, cy = rect.center
            w, h = rect.size
            r = min(w, h) * SYMBOL_CIRCLE_RADIUS_FACTOR
            if name == "CIRCLE":
                pygame.draw.circle(surface, color, (int(cx), int(cy)), int(r), thickness)
            elif name == "SQUARE":
                side = r * 1.6
                rr = pygame.Rect(0, 0, side, side)
                rr.center = rect.center
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

    def _draw_label_value_vstack(self, *, label: str, value: str, left: bool, anchor_rect: pygame.Rect) -> None:
        label_surf = self.hud_label_font.render(label, True, HUD_LABEL_COLOR)
        value_surf = self.hud_value_font.render(value, True, HUD_VALUE_COLOR)
        total_h = label_surf.get_height() + 2 + value_surf.get_height()
        y = anchor_rect.centery - total_h // 2
        if left:
            lx = vx = anchor_rect.left
        else:
            lx = anchor_rect.right - label_surf.get_width()
            vx = anchor_rect.right - value_surf.get_width()

        # shadow
        self.screen.blit(label_surf, (lx + 1, y + 1))
        self.screen.blit(value_surf, (vx + 2, y + label_surf.get_height() + 3))
        # main text
        self.screen.blit(label_surf, (lx, y))
        self.screen.blit(value_surf, (vx, y + label_surf.get_height() + 2))

    def _draw_label_value_vstack_center(self, *, label: str, value: str, anchor_rect: pygame.Rect) -> None:
        label_surf = self.hud_label_font.render(label, True, HUD_LABEL_COLOR)
        value_surf = self.hud_value_font.render(value, True, HUD_VALUE_COLOR)
        gap = 2
        total_h = label_surf.get_height() + gap + value_surf.get_height()

        y = anchor_rect.centery - total_h // 2
        lx = anchor_rect.centerx - label_surf.get_width() // 2
        vx = anchor_rect.centerx - value_surf.get_width() // 2

        # lekki cień
        self.screen.blit(label_surf, (lx + 1, y + 1))
        self.screen.blit(value_surf, (vx + 2, y + label_surf.get_height() + 3))
        # tekst
        self.screen.blit(label_surf, (lx, y))
        self.screen.blit(value_surf, (vx, y + label_surf.get_height() + gap))

    def _draw_settings_row(self, *, label: str, value: str, y: float, selected: bool) -> float:
        font = self.settings_font
        axis_x = self.w // 2
        gap = self.px(SETTINGS_CENTER_GAP) 

        col_label = ACCENT if selected else INK
        col_value = ACCENT if selected else INK

        label_surf = font.render(label, True, col_label)   # <-- was missing
        value_surf = font.render(value, True, col_value)

        lh = label_surf.get_height()
        vh = value_surf.get_height()
        row_h = max(lh, vh)

        label_x = axis_x - gap - label_surf.get_width()
        label_y = y + (row_h - lh) / 2

        value_x = axis_x + gap
        value_y = y + (row_h - vh) / 2

        # subtle shadow + text
        self.screen.blit(self._shadow_text(label_surf), (label_x + 2, label_y + 2))
        self.screen.blit(label_surf, (label_x, label_y))

        self.screen.blit(self._shadow_text(value_surf), (value_x + 2, value_y + 2))
        self.screen.blit(value_surf, (value_x, value_y))

        return row_h

    def _render_rule_panel_surface(
        self,
        pair: Tuple[str, str],
        panel_scale: float,
        symbol_scale: float,
        *,
        label_font: Optional[pygame.font.Font] = None,
    ) -> tuple[pygame.Surface, pygame.Surface]:
        panel_scale = max(0.2, float(panel_scale))
        symbol_scale = max(0.2, float(symbol_scale))

        # Title
        title_font = label_font or self.mid
        title_surf = title_font.render(RULE_BANNER_TITLE, True, ACCENT)
        title_w, title_h = title_surf.get_size()

        # Icon/arrow sizes determined by screen width and symbol scale
        icon_size = int(self.w * RULE_ICON_SIZE_FACTOR * symbol_scale)
        icon_gap = int(self.w * RULE_ICON_GAP_FACTOR * symbol_scale)
        arrow_w = int(icon_size * 1.05)
        arrow_h = int(icon_size * 0.55)
        icon_line_h = max(icon_size, arrow_h)
        icon_line_w = icon_size + icon_gap + arrow_w + icon_gap + icon_size

        # Raw, unscaled inner dimensions
        inner_w = max(title_w, icon_line_w)
        inner_h = RULE_BANNER_VGAP + title_h + RULE_BANNER_VGAP + icon_line_h + RULE_BANNER_VGAP

        panel_w_raw = max(inner_w + 2 * RULE_PANEL_PAD, int(self.w * RULE_BANNER_MIN_W_FACTOR))
        panel_h_raw = inner_h + 2 * RULE_PANEL_PAD

        # Final scaled panel size
        panel_w = max(1, int(panel_w_raw * panel_scale))
        panel_h = max(1, int(panel_h_raw * panel_scale))

        # Draw at scale 1.0 for crisp text, then smoothscale
        panel_raw = pygame.Surface((panel_w_raw, panel_h_raw), pygame.SRCALPHA)
        shadow_raw = pygame.Surface((panel_w_raw, panel_h_raw), pygame.SRCALPHA)

        pygame.draw.rect(shadow_raw, (0, 0, 0, 120), shadow_raw.get_rect(), border_radius=RULE_PANEL_RADIUS + 2)
        pygame.draw.rect(panel_raw, RULE_PANEL_BG, panel_raw.get_rect(), border_radius=RULE_PANEL_RADIUS)
        pygame.draw.rect(
            panel_raw,
            RULE_PANEL_BORDER,
            panel_raw.get_rect(),
            width=RULE_PANEL_BORDER_W,
            border_radius=RULE_PANEL_RADIUS,
        )

        # Positions
        cx = panel_w_raw // 2
        y = RULE_PANEL_PAD + RULE_BANNER_VGAP
        panel_raw.blit(title_surf, (cx - title_w // 2, y))
        y += title_h + RULE_BANNER_VGAP

        line_left = cx - icon_line_w // 2
        cy = y + icon_line_h // 2

        left_rect = pygame.Rect(0, 0, icon_size, icon_size)
        right_rect = pygame.Rect(0, 0, icon_size, icon_size)
        arrow_rect = pygame.Rect(0, 0, arrow_w, arrow_h)
        left_rect.center = (line_left + icon_size // 2, cy)
        arrow_rect.center = (line_left + icon_size + icon_gap + arrow_w // 2, cy)
        right_rect.center = (line_left + icon_size + icon_gap + arrow_w + icon_gap + icon_size // 2, cy)

        # Draw rule (symbol → symbol)
        self.draw_symbol(panel_raw, pair[0], left_rect)
        self.draw_arrow(panel_raw, arrow_rect)
        self.draw_symbol(panel_raw, pair[1], right_rect)

        # Scale the complete panel + shadow
        panel = pygame.transform.smoothscale(panel_raw, (panel_w, panel_h))
        shadow = pygame.transform.smoothscale(shadow_raw, (panel_w, panel_h))
        return panel, shadow

    def _draw_rule_banner_anim(self) -> None:
        pair = self.rules.current_mapping
        if not pair:
            return
        now = self.now()
        phase, p = self.banner.phase(now)

        mid_y = int(self.h * 0.30)
        pinned_y = int(getattr(self, "_rule_pinned_y", self.topbar_rect.bottom + int(self.h * 0.02)))

        if phase == "in" and getattr(self.banner, "from_pinned", False):
            panel_scale = RULE_BANNER_PIN_SCALE + (1.0 - RULE_BANNER_PIN_SCALE) * self._ease_out_cubic(p)
            symbol_scale = RULE_SYMBOL_SCALE_PINNED + (RULE_SYMBOL_SCALE_CENTER - RULE_SYMBOL_SCALE_PINNED) * self._ease_out_cubic(p)
            y = int(pinned_y + (mid_y - pinned_y) * self._ease_out_cubic(p))
            font = self.rule_font_center
        elif phase == "in":
            panel_scale, symbol_scale, font = 1.0, RULE_SYMBOL_SCALE_CENTER, self.rule_font_center
            start_y = -int(self.h * 0.35)
            y = int(start_y + (mid_y - start_y) * self._ease_out_cubic(p))
        elif phase == "hold":
            panel_scale, symbol_scale, font = 1.0, RULE_SYMBOL_SCALE_CENTER, self.rule_font_center
            y = mid_y
            self.banner.from_pinned = False
        else:
            panel_scale = 1.0 + (RULE_BANNER_PIN_SCALE - 1.0) * self._ease_out_cubic(p)
            symbol_scale = RULE_SYMBOL_SCALE_CENTER + (RULE_SYMBOL_SCALE_PINNED - RULE_SYMBOL_SCALE_CENTER) * self._ease_out_cubic(p)
            y = int(mid_y + (pinned_y - mid_y) * self._ease_out_cubic(p))
            font = self.rule_font_pinned

        panel_scale *= self.fx.pulse_scale('banner')
        panel, shadow = self._render_rule_panel_surface(pair, panel_scale, symbol_scale, label_font=font)
        panel_w, panel_h = panel.get_size()
        panel_x = (self.w - panel_w) // 2
        self.screen.blit(shadow, (panel_x + 3, y + 5))
        self.screen.blit(panel, (panel_x, y))

    def _draw_rule_banner_pinned(self) -> None:
        pair = self.rules.current_mapping
        if not pair:
            return
        panel_scale = RULE_BANNER_PIN_SCALE * self.fx.pulse_scale('banner')
        symbol_scale = RULE_SYMBOL_SCALE_PINNED
        panel, shadow = self._render_rule_panel_surface(pair, panel_scale, symbol_scale, label_font=self.rule_font_pinned)
        panel_w, panel_h = panel.get_size()
        panel_x = (self.w - panel_w) // 2
        panel_y = int(getattr(self, "_rule_pinned_y", self.topbar_rect.bottom + int(self.h * 0.02)))
        self.screen.blit(shadow, (panel_x + 3, panel_y + 5))
        self.screen.blit(panel, (panel_x, panel_y))

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

        # background
        pygame.draw.rect(self.screen, TIMER_BAR_BG,
                         (bar_x, bar_y, bar_w, bar_h),
                         border_radius=TIMER_BAR_BORDER_RADIUS)
        # fill
        fill_w = int(bar_w * ratio)
        if fill_w > 0:
            pygame.draw.rect(self.screen, fill_color,
                             (bar_x, bar_y, fill_w, bar_h),
                             border_radius=TIMER_BAR_BORDER_RADIUS)
        # border
        pygame.draw.rect(self.screen, TIMER_BAR_BORDER,
                         (bar_x, bar_y, bar_w, bar_h),
                         width=TIMER_BAR_BORDER_W,
                         border_radius=TIMER_BAR_BORDER_RADIUS)

        # position tick
        indicator_x = max(bar_x, min(bar_x + bar_w, bar_x + fill_w))
        indicator_rect = pygame.Rect(
            indicator_x - TIMER_POSITION_INDICATOR_W // 2,
            bar_y - TIMER_POSITION_INDICATOR_PAD,
            TIMER_POSITION_INDICATOR_W,
            bar_h + TIMER_POSITION_INDICATOR_PAD * 2,
        )
        pygame.draw.rect(self.screen, ACCENT, indicator_rect)

        # label above
        if label:
            timer_font = getattr(self, "timer_font", self.mid)
            lw, lh = timer_font.size(label)
            tx = bar_x + (bar_w - lw) // 2
            ty = bar_y - lh - TIMER_LABEL_GAP
            self.screen.blit(timer_font.render(label, True, (0, 0, 0)), (tx + 2, ty + 2))
            self.screen.blit(timer_font.render(label, True, TIMER_BAR_TEXT_COLOR), (tx, ty))

    def _draw_hud(self) -> None:
        # Header underline (cyan)
        # --- underline split to avoid drawing under the SCORE capsule ---
        cap = self.score_capsule_rect
        y   = self.topbar_rect.bottom - TOPBAR_UNDERLINE_THICKNESS // 2
        th  = TOPBAR_UNDERLINE_THICKNESS
        col = TOPBAR_UNDERLINE_COLOR

        left_end    = max(self.topbar_rect.left, cap.left - 1)
        right_start = min(self.topbar_rect.right, cap.right + 1)

        # lewy odcinek
        if left_end > self.topbar_rect.left:
            pygame.draw.line(self.screen, col,
                            (self.topbar_rect.left, y), (left_end, y), th)
        # prawy odcinek
        if right_start < self.topbar_rect.right:
            pygame.draw.line(self.screen, col,
                            (right_start, y), (self.topbar_rect.right, y), th)

        # --- STREAK (lewo) / HIGHSCORE (prawo) liczone względem kapsuły SCORE ---
        pad_x = int(self.w * TOPBAR_PAD_X_FACTOR)
        cap = self.score_capsule_rect

        # lewa zatoka: od lewego marginesu do lewej krawędzi kapsuły
        left_block = pygame.Rect(
            pad_x,
            self.topbar_rect.top,
            max(1, cap.left - pad_x * 2),
            self.topbar_rect.height,
        )

        # prawa zatoka: od prawej krawędzi kapsuły do prawego marginesu
        right_block = pygame.Rect(
            cap.right + pad_x,
            self.topbar_rect.top,
            max(1, self.w - pad_x - (cap.right + pad_x)),
            self.topbar_rect.height,
        )

        # === STREAK z pulsem na wartości ===
        streak_label = "STREAK"
        streak_value = str(self.streak)

        # etykieta (bez skali)
        label_surf = self.hud_label_font.render(streak_label, True, HUD_LABEL_COLOR)
        label_x = left_block.centerx - label_surf.get_width() // 2
        label_y = left_block.centery - label_surf.get_height() - 2
        # cień + tekst
        self.screen.blit(label_surf, (label_x + 1, label_y + 1))
        self.screen.blit(label_surf, (label_x, label_y))

        # wartość – render i ewentualne skalowanie (pulse)
        value_surf = self.hud_value_font.render(streak_value, True, HUD_VALUE_COLOR)
        scale = self.fx.pulse_scale('streak')
        if scale != 1.0:
            vw, vh = value_surf.get_size()
            sw, sh = max(1, int(vw * scale)), max(1, int(vh * scale))
            value_surf = pygame.transform.smoothscale(value_surf, (sw, sh))

        vx = left_block.centerx - value_surf.get_width() // 2
        vy = label_y + label_surf.get_height() + 2
        self.screen.blit(self._shadow_text(value_surf), (vx + 2, vy + 2))
        self.screen.blit(value_surf, (vx, vy))

        # HIGHSCORE po prawej (bez zmian)
        self._draw_label_value_vstack_center(
            label="HIGHSCORE", value=str(self.highscore), anchor_rect=right_block
        )

        # --- kapsuła SCORE ---
        sx, sy = SCORE_CAPSULE_SHADOW_OFFSET
        shadow_rect = cap.move(sx, sy)
        self._draw_round_rect(self.screen, shadow_rect, SCORE_CAPSULE_SHADOW, radius=SCORE_CAPSULE_RADIUS + 2)
        self._draw_round_rect(
            self.screen, cap, SCORE_CAPSULE_BG,
            border=SCORE_CAPSULE_BORDER_COLOR, border_w=2, radius=SCORE_CAPSULE_RADIUS
        )
        label_surf = self.score_label_font.render("SCORE", True, SCORE_LABEL_COLOR)
        value_surf = self.score_value_font.render(str(self.score), True, self.level_value_color())
        gap = 2
        total_h = label_surf.get_height() + gap + value_surf.get_height()
        lx = cap.centerx - label_surf.get_width() // 2
        vx = cap.centerx - value_surf.get_width() // 2
        ly = cap.centery - total_h // 2
        vy = ly + label_surf.get_height() + gap
        self.screen.blit(label_surf, (lx + 1, ly + 1))
        self.screen.blit(value_surf, (vx + 1, vy + 1))
        self.screen.blit(label_surf, (lx, ly))
        self.screen.blit(value_surf, (vx, vy))

        # docelowe Y dla dockowania bannera: poniżej kapsuły SCORE
        margin = self.px(RULE_BANNER_PINNED_MARGIN)
        self._rule_pinned_y = max(self.topbar_rect.bottom + self.px(8), self.score_capsule_rect.bottom + margin)

        # Bottom timer (only in-game)
        if self.scene is Scene.GAME:
            if self.mode is Mode.TIMED:
                self._draw_timer_bar_bottom(self.time_left / TIMED_DURATION, f"{self.time_left:.1f}s")
            elif self.mode is Mode.SPEEDUP and self.target_deadline is not None and self.target_time > 0:
                remaining = max(0.0, self.target_deadline - self.now())
                ratio = remaining / max(0.001, self.target_time)
                self._draw_timer_bar_bottom(ratio, f"{remaining:.1f}s")

    def _blit_bg(self):
        if self.bg_img:
            self.screen.blit(self.bg_img, (0, 0))
        else:
            self.screen.fill(BG)

    def _draw_input_ring(self, center: tuple[int, int], base_size: int) -> None:
        cx, cy = center
        r = int(base_size * RING_RADIUS_FACTOR)

        # ring
        surf = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        pygame.draw.circle(surf, RING_COLOR, (cx, cy), r, RING_THICKNESS)
        self.screen.blit(surf, (0, 0))

        pos_xy = {
            "TOP":    (cx, cy - r),
            "RIGHT":  (cx + r, cy),
            "LEFT":   (cx - r, cy),
            "BOTTOM": (cx, cy + r),
        }
        icon_size = int(base_size * RING_ICON_SIZE_FACTOR)

        # jeśli memory i ikony mają być ukryte – nic nie rysujemy na ringu
        if self.level_cfg.memory_mode and not self.memory_show_icons:
            return

        for pos, (ix, iy) in pos_xy.items():
            name = self.ring_layout.get(pos, DEFAULT_RING_LAYOUT[pos])
            rect = pygame.Rect(0, 0, icon_size, icon_size)
            rect.center = (ix, iy)
            self.draw_symbol(self.screen, name, rect)

    def _draw_spawn_animation(self, surface: pygame.Surface, name: str, rect: pygame.Rect) -> None:
        age = self.now() - self.symbol_spawn_time
        t = 0.0 if SYMBOL_ANIM_TIME <= 0 else min(1.0, max(0.0, age / SYMBOL_ANIM_TIME))
        eased = 1.0 - (1.0 - t) ** 3

        base_size = self.w * SYMBOL_BASE_SIZE_FACTOR
        scale = SYMBOL_ANIM_START_SCALE + (1.0 - SYMBOL_ANIM_START_SCALE) * eased
        scale *= self.fx.pulse_scale('symbol')             # << pulsing z FX
        size = int(base_size * scale)

        start_y = self.h * (0.5 + SYMBOL_ANIM_OFFSET_Y)
        end_y = self.h * 0.5
        cy = start_y + (end_y - start_y) * eased

        dx, dy = self.fx.shake_offset(self.w)              # << shake z FX

        draw_rect = pygame.Rect(0, 0, size, size)
        draw_rect.center = (int(self.w * 0.5 + dx), int(cy + dy))
        self.draw_symbol(surface, name, draw_rect)

    def _draw_gameplay(self):
        self._blit_bg()
        self._draw_hud()

        if self.target:
            base_rect = pygame.Rect(0, 0, self.w * SYMBOL_BASE_SIZE_FACTOR, self.w * SYMBOL_BASE_SIZE_FACTOR)
            base_rect.center = (self.w * 0.5, self.h * 0.5)

            # ring dookoła symbolu (bez podświetleń)
            self._draw_input_ring(base_rect.center, base_rect.width)

            # symbol centralny
            self._draw_spawn_animation(self.screen, self.target, base_rect)

        if self.rules.current_mapping and not self.banner.is_active(self.now()):
            self._draw_rule_banner_pinned()

    def draw(self):
        self.fb.fill((0, 0, 0, 0))
        old_screen = self.screen
        self.screen = self.fb
        try:
            if self.scene is Scene.GAME and self.rules.current_mapping and self.banner.is_active(self.now()):
                self._blit_bg()
                self._draw_rule_banner_anim()

            elif self.scene is Scene.GAME:
                self._draw_gameplay()

            elif self.scene is Scene.MENU:
                self._blit_bg()
                title_text = "Remap"
                tw, th = self.big.size(title_text)
                tx = self.w / 2 - tw / 2
                ty = self.h * MENU_TITLE_Y_FACTOR
                mode_gap  = self.px(MENU_MODE_GAP)
                hint_gap  = self.px(MENU_HINT_GAP)
                hint2_gap = self.px(MENU_HINT2_EXTRA_GAP)
                self.draw_text(self.big, title_text, (tx, ty))

                mode_label = "SPEED-UP" if self.mode is Mode.SPEEDUP else "TIMED"
                mode_text = f"Mode: {mode_label}  (M = change)"
                mw, mh = self.mid.size(mode_text)
                self.draw_text(self.mid, mode_text, (self.w/2 - mw/2,  ty + th + mode_gap), color=ACCENT)

                hint_text = "ENTER = start   ·   ESC/Q = quit"
                hw, hh = self.font.size(hint_text)
                self.draw_text(self.font, hint_text, (self.w/2 - hw/2,  ty + th + hint_gap + mh))

                hint2_text = "O = settings"
                h2w, h2h = self.font.size(hint2_text)
                self.draw_text(self.font, hint2_text,(self.w/2 - h2w/2, ty + th + hint_gap + mh + hh + hint2_gap))

            elif self.scene is Scene.OVER:
                over_title_off = self.px(OVER_TITLE_OFFSET_Y)
                score_gap1     = self.px(OVER_SCORE_GAP1)
                score_gap2     = self.px(OVER_SCORE_GAP2)
                over_info_gap  = self.px(OVER_INFO_GAP)

                self._blit_bg()
                over_text = "GAME OVER"
                ow, oh = self.big.size(over_text)
                self.draw_text(self.big, over_text, (self.w/2 - ow/2, self.h/2 - oh/2 + over_title_off))

                score_text = f"Score: {self.score}"
                best_text  = f"Best:  {self.highscore}"
                sw, sh = self.mid.size(score_text)
                bw, bh = self.mid.size(best_text)
                self.draw_text(self.mid, score_text, (self.w/2 - sw/2, self.h/2 - sh/2 + score_gap1), color=ACCENT)
                self.draw_text(self.mid, best_text, (self.w/2 - bw/2, self.h/2 - bh/2 + score_gap2), color=ACCENT)

                info_text = "SPACE = play again   ·   ESC = quit"
                iw, ih = self.font.size(info_text)
                self.draw_text(self.font, info_text, (self.w/2 - iw/2, self.h/2 + over_info_gap))

            elif self.scene is Scene.SETTINGS:
                self._blit_bg()
                title_text = "Settings"
                tw, th = self.big.size(title_text)
                self.draw_text(self.big, title_text, (self.w / 2 - tw / 2, self.h * SETTINGS_TITLE_Y_FACTOR))

                y = self.h * SETTINGS_LIST_Y_START_FACTOR
                item_spacing = self.px(SETTINGS_ITEM_SPACING)

                for i, (label, value, key) in enumerate(self.settings_items()):
                    selected = (i == self.settings_idx and key is not None)
                    row_h = self._draw_settings_row(label=label, value=value, y=y, selected=selected)
                    y += row_h + item_spacing

                help1 = "↑/↓ select · ←/→ adjust · R reset high score"
                help2 = "ENTER save · ESC back"

                help_margin = self.px(SETTINGS_HELP_MARGIN_TOP)
                help_gap    = self.px(SETTINGS_HELP_GAP)

                w1, h1 = self.font.size(help1)
                w2, h2 = self.font.size(help2)
                self.draw_text(self.font, help1, (self.w / 2 - w1 / 2, y + help_margin))
                self.draw_text(self.font, help2, (self.w / 2 - w2 / 2, y + help_margin + h1 + help_gap))
            
            elif self.scene is Scene.INSTRUCTION:
                self._blit_bg()
                lines = (self.instruction_text or f"LEVEL {self.level}").splitlines()
                y = self.h * 0.30
                for i, L in enumerate(lines):
                    f = self.big if i == 0 else self.mid
                    tw, th = f.size(L)
                    self.draw_text(f, L, (self.w/2 - tw/2, y))
                    y += th + self.px(10)
                hint = "ENTER/SPACE = start"
                hw, hh = self.font.size(hint)
                self.draw_text(self.font, hint, (self.w/2 - hw/2, y + self.px(24)), color=ACCENT)

        finally:
            self.screen = old_screen

        # post FX + present
        final_surface = self.fx.apply_postprocess(self.fb, self.w, self.h)
        self.screen.blit(final_surface, (0, 0))
        pygame.display.flip()

# ============================== MAIN LOOP ============================== #

def main():
    """Program entry. Sets up window, game object, GPIO (optional) and the loop."""
    os.environ['SDL_VIDEO_WINDOW_POS'] = "0,0"
    pygame.init()
    pygame.key.set_repeat()
    fullscreen = bool(CFG.get("display", {}).get("fullscreen", True))
    screen = pygame.display.set_mode((1, 1))  # tiny placeholder; real size set next
    game = Game(screen, mode=Mode.SPEEDUP)
    game._set_display_mode(fullscreen)
    pygame.display.set_caption("Remap")
    iq = InputQueue()
    _ = init_gpio(iq)

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit(0)
            game.handle_event(event, iq)
        game.update(iq)
        game.draw()
        game.clock.tick(FPS)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pygame.quit(); sys.exit(0)
