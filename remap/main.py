from __future__ import annotations

import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pygame

from .config import CFG, save_config, persist_windowed_size
from .settings import make_runtime_settings, clamp_settings, commit_settings

PKG_DIR = Path(__file__).resolve().parent

# ========= IMAGE LOADER (cache) =========

class ImageStore:
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
            return None

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
INK = (235, 235, 235)            # podstawowy kolor tekstu
ACCENT = (255, 210, 90)          # akcent (nagłówki, ważne etykiety)

# Kolory wektorowych symboli, jeśli brak tekstur PNG
SYMBOL_COLORS = {
    "TRIANGLE": (0, 0, 255),   
    "CIRCLE":   (255, 0, 0),
    "CROSS":    (0, 255, 0),   
    "SQUARE":   (255, 215, 0),
}

# Ogólne odstępy/układ
PADDING = 0.06                   # margines sceny (proporcja szer./wys. okna)
GAP = 0.04                       # przerwa między obiektami w siatce
FPS = CFG["display"]["fps"]      # docelowy FPS (z configu)
INPUT_ACCEPT_DELAY = 0.12
TEXT_SHADOW_OFFSET = (2, 2)
UI_RADIUS = 8

# --- Levels --- (progresja poziomów)
LEVEL_GOAL_PER_LEVEL = 15        # ile trafień, by wskoczyć na kolejny poziom
LEVELS_ACTIVE_FOR_NOW = 7        # faktycznie używana liczba poziomów
LEVELS_MAX = 10

# Tempo gry i tryby
TARGET_TIME_INITIAL = CFG["speedup"]["target_time_initial"]  # startowy czas na reakcję (tryb SPEEDUP)
TARGET_TIME_MIN = CFG["speedup"]["target_time_min"]          # dolne ograniczenie czasu reakcji
TARGET_TIME_STEP = CFG["speedup"]["target_time_step"]        # zmiana czasu po każdym trafieniu
TIMED_DURATION = CFG["timed"]["duration"]                    # czas całej rundy w trybie TIMED
RULE_EVERY_HITS = CFG["rules"]["every_hits"]                 # co ile trafień losujemy nową regułę (poziom 2+)
MAX_LIVES = CFG["lives"]                                     # liczba żyć w SPEEDUP (jeśli >0)
ADDITIONAL_RULE_TIME = float(CFG["timed"].get("rule_bonus", 5.0))  # bonus sekund po wylosowaniu reguły (TIMED)

# Rozmiar i animacja symbolu celu
CENTER_Y_FACTOR = 0.58            # pozycja centralnego symbolu
SYMBOL_BASE_SIZE_FACTOR = 0.28    # bazowy rozmiar symbolu (proporcja szerokości okna)
SYMBOL_ANIM_TIME = 0.30           # czas dojścia animacji skali/pozycji do 100%
SYMBOL_ANIM_START_SCALE = 0.20    # początkowa skala podczas spawn
SYMBOL_ANIM_OFFSET_Y = 0.08       # startowe przesunięcie w dół (proporcja wysokości)

# Efekt potrząśnięcia (shake) kamery
SHAKE_DURATION = 0.12             # długość wstrząsu
SHAKE_AMPLITUDE_FACT = 0.012      # amplituda (proporcja szerokości okna)
SHAKE_FREQ_HZ = 18.0              # częstotliwość drgań

# Parametry rysowania symboli wektorowych (fallback)
SYMBOL_DRAW_THICKNESS = 20        # grubość linii
SYMBOL_SQUARE_RADIUS = UI_RADIUS  # promień zaokrąglenia kwadratu
SYMBOL_CIRCLE_RADIUS_FACTOR = 0.32        # promień koła względem mniejszego boku recta
SYMBOL_TRIANGLE_POINT_FACTOR = 0.9        # „ostrość” trójkąta
SYMBOL_CROSS_K_FACTOR = 1.0               # długość ramion krzyżyka (krotność promienia)

# --- Glitch --- (efekt post-process)
GLITCH_DURATION = 0.20            # długość pojedynczego glitcha
GLITCH_PIXEL_FACTOR_MAX = 0.10    # maks. pikselizacja (skala downsample)

# --- Text Glitch --- (zakłócenia napisów)
TEXT_GLITCH_DURATION = 0.5        # jak długo trwa glitch tekstu
TEXT_GLITCH_MIN_GAP = 1           # min przerwa między glitchami
TEXT_GLITCH_MAX_GAP = 5.0         # max przerwa między glitchami
TEXT_GLITCH_CHAR_PROB = 0.01      # prawdopodobieństwo podmiany znaku
TEXT_GLITCH_CHARSET = "01+-_#@$%&*[]{}<>/\\|≈≠∆░▒▓"  # z jakich znaków mieszamy

EXIT_SLIDE_SEC = 0.18             # szybki „zjazd” po poprawnej odpowiedzi
INSTRUCTION_FADE_IN_SEC = 1    # fade na poczatku instukcji zeby nie bylo gwaltownego wejscia

# --- Pulse (FX) ---
# Baza + per-element modyfikatory (łatwe strojenie intensywności z jednego miejsca)
PULSE_BASE_DURATION = 0.30        # ogólna długość pulsu (s)
PULSE_BASE_MAX_SCALE = 1.18       # ogólny maks. scale (1.0 = brak)

# mnożniki skali względem bazy (1.0 = taki sam jak baza)
PULSE_KIND_SCALE = {
    "symbol": 1.00,    # puls centralnego symbolu (połowa czasu na reakcję)
    "streak": 1.06,    # puls licznika streak co X trafień
    "banner": 1.04,    # delikatny puls banera gdy „trafisz pod mapping”
    "score":  1.10,    # puls liczby SCORE po zdobyciu punktu
    "timer":  1.10,    # puls paska z czasem
}

# czas trwania per-element (jeśli nie podasz, użyje PULSE_BASE_DURATION)
PULSE_KIND_DURATION = {
    "symbol": 0.30,
    "streak": 0.30,
    "banner": 0.30,
    "score":  0.26,
    "timer":  0.40
}

# --- Timer bar (bottom) --- (pasek czasu na dole ekranu)
TIMER_BAR_WIDTH_FACTOR = 0.66     # szerokość paska względem szerokości okna
TIMER_BAR_HEIGHT = 18             # wysokość paska w px
TIMER_BAR_BG = (40, 40, 50)       # kolor tła paska
TIMER_BAR_FILL = (90, 200, 255)   # kolor wypełnienia (normalny)
TIMER_BAR_BORDER = (160, 180, 200)# kolor ramki
TIMER_BAR_BORDER_W = 2            # grubość ramki
TIMER_BAR_WARN_COLOR = (255, 170, 80)  # kolor ostrzegawczy (mało czasu)
TIMER_BAR_CRIT_COLOR = (220, 80, 80)   # kolor krytyczny (bardzo mało czasu)
TIMER_BAR_WARN_TIME = 0.50        # próg ostrzegawczy (ułamek 0–1)
TIMER_BAR_CRIT_TIME = 0.25        # próg krytyczny (ułamek 0–1)
TIMER_BAR_BORDER_RADIUS = UI_RADIUS     # zaokrąglenie rogów paska
TIMER_BOTTOM_MARGIN_FACTOR = 0.02 # odległość paska od dołu ekranu (proporcja wys.)
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
RULE_BANNER_PIN_SCALE = 0.65      # skala panelu po „zadokowaniu” u góry
RULE_SYMBOL_SCALE_CENTER = 1.00   # skala symboli w centrum
RULE_SYMBOL_SCALE_PINNED = 0.70   # skala symboli po dokowaniu
RULE_BANNER_MIN_W_FACTOR = 0.90   # minimalna szerokość panelu względem ekranu
RULE_BANNER_FONT_CENTER_PX = 64
RULE_BANNER_FONT_PINNED_PX = 40

# --- Memory (ring hide conditions) ---
MEMORY_HIDE_AFTER_MOVES = 1      # po ilu ruchach znikają ikony
MEMORY_HIDE_AFTER_SEC   = 3.0    # po ilu sekundach znikają ikony

# --- Input Ring (wokół symbolu celu)
RING_RADIUS_FACTOR = 1           # promień ringu jako ułamek rozmiaru docelowego symbolu
RING_THICKNESS = 6               # grubość okręgu
RING_ICON_SIZE_FACTOR = 0.46     # rozmiar ikon na ringu względem symbolu w centrum
RING_ALPHA_MAIN  = 245           # główny łuk
RING_ALPHA_SOFT  = 220           # delikatny łuk/warstwy
RING_ALPHA_TICKS = 200           # „kreski” / znaczniki
RING_ALPHA_HI    = 255           # akcent (scanner)

# --- Ring layout (pozycje) ---
DEFAULT_RING_LAYOUT = {
    "TOP": "TRIANGLE",
    "RIGHT": "CIRCLE",
    "LEFT": "SQUARE",
    "BOTTOM": "CROSS",
}

MOD_COLOR = {
    "remap":   (236, 72, 153),   # magenta
    "spin":    (255, 210, 90),   # gold
    "memory":  (220, 80, 80),    # red
    "invert":  (90, 200, 120),   # green (inverted joystick)
}

RING_POSITIONS = ["TOP", "RIGHT", "LEFT", "BOTTOM"]

RING_PALETTES = {
    "clean-white":   {"base": (243,244,246), "hi": (255,255,255), "soft": (209,213,219)},
    "electric-blue": {"base": (96,165,250),  "hi": (37,99,235),   "soft": (147,197,253)},
    "neon-cyan":     {"base": (103,232,249), "hi": (34,211,238),  "soft": (165,243,252)},
    "violet-neon":   {"base": (167,139,250), "hi": (139,92,246),  "soft": (196,181,253)},
    "magenta":       {"base": (236,72,153),  "hi": (219,39,119),  "soft": (249,168,212)},
    "gold":          {"base": (255,210,90),  "hi": (255,230,140), "soft": (245,195,70)},  # używane tylko po pobiciu HS
}

# tor dla AUTO (od startu do highscore)
RING_GRADIENT_ORDER = ["clean-white", "electric-blue", "neon-cyan", "violet-neon", "magenta"]

# --- Screens --- (rozmieszczenie elementów w ekranach MENU/OVER/SETTINGS)
MENU_TITLE_Y_FACTOR = 0.28           # pionowe położenie tytułu w MENU (proporcja wys.)
MENU_MODE_GAP = 20                   # odstęp tytuł → wiersz „Mode:” (px; w kodzie skalowany)
MENU_HINT_GAP = 48                   # odstęp do pierwszej podpowiedzi
MENU_HINT2_EXTRA_GAP = 12            # dodatkowy odstęp do drugiej podpowiedzi
SETTINGS_TABLE_MAX_W = 1100          # maksymalna szerokość tabeli (tylko w landscape)

# --- Menu: styl tytułu REMAP ---
MENU_TITLE_GLOBAL_SCALE = 1.18
MENU_TITLE_PRIMARY_COLOR = INK                 # kolor liter
MENU_TITLE_NEON_COLOR = (90, 200, 255, 75)     # delikatna poświata za tytułem
MENU_TITLE_NEON_LAYERS = 4                     # ile „rozmytych” warstw poświaty
MENU_TITLE_NEON_SCALE_STEP = 0.08              # jak szeroko rośnie każda warstwa poświaty
MENU_SUBTLE_TEXT_COLOR = (210, 210, 220)       # kolor tekstów pomocniczych
MENU_CHIP_BG = (20, 22, 30, 160)               # tło żetonu „chip”
MENU_CHIP_BORDER = (120, 200, 255, 200)
MENU_CHIP_RADIUS = 14
MENU_TITLE_TRIANGLE_COLOR = (120, 210, 255)      # delikatny cyjan
MENU_TITLE_GLOW_COLOR = (120, 210, 255, 60)      # poświata za tytułem
MENU_TITLE_GLOW_PASSES = 2                       # ile powiększonych „kopii” do poświaty
MENU_TITLE_GLOW_SCALE = 1.12                     # skala poświaty (1.0 = brak)
MENU_TITLE_TRIANGLE_SCALE = 0.82                 # wielkość trójkąta względem wysokości linii
MENU_TITLE_LETTER_SPACING = 0.012                # tracking pomiędzy segmentami

MENU_MODE_BADGE_BG = (22, 26, 34, 120)          # tło małego badge pod tytułem
MENU_MODE_BADGE_BORDER = (120, 200, 255, 110)    # cienka ramka
MENU_MODE_BADGE_RADIUS = 10
MENU_MODE_TEXT_COLOR = (225, 230, 240)           # subtelny tekst

OVER_TITLE_OFFSET_Y = -60            # przesunięcie tytułu „GAME OVER”
OVER_SCORE_GAP1 = -10                # przesunięcie pierwszej linii wyniku
OVER_SCORE_GAP2 = 26                 # przesunięcie drugiej linii wyniku
OVER_INFO_GAP = 60                   # odstęp do linii z instrukcją
SETTINGS_TITLE_Y_FACTOR = 0.10       # pionowe położenie tytułu „Settings”
SETTINGS_LIST_Y_START_FACTOR = 0.23  # start Y listy opcji
SETTINGS_ITEM_SPACING = 3            # odstęp między wierszami listy
SETTINGS_HELP_MARGIN_TOP = 18        # margines nad helpem na dole
SETTINGS_HELP_GAP = 6                # odstęp między wierszami helpu
SETTINGS_CENTER_GAP = 12             # odstęp między etykietą a wartością w wierszu

# --- Top Header & Score Capsule --- (górny HUD)
TOPBAR_HEIGHT_FACTOR = 0.095                    # wysokość topbara (proporcja wys. okna)
TOPBAR_PAD_X_FACTOR = 0.045                     # poziomy padding lewej/prawej sekcji
TOPBAR_UNDERLINE_THICKNESS = 4                  # grubość linii pod topbarem
TOPBAR_UNDERLINE_COLOR = (90, 200, 255)         # kolor linii
TOPBAR_UNDERLINE_SHADOW_COLOR = (0, 0, 0, 140)  # kolor i alfa cienia
TOPBAR_UNDERLINE_SHADOW_OFFSET = (2, 3)         # (dx, dy) przesunięcia w dół/prawo
TOPBAR_UNDERLINE_SHADOW_EXTRA_THICK = 3         # cień jest trochę grubszy niż linia
TOPBAR_UNDERLINE_SHADOW_RADIUS = 2              # lekkie zaokrąglenie krawędzi

SCORE_CAPSULE_WIDTH_FACTOR = 0.42                   # szerokość kapsuły wyniku (proporcja szer.)
SCORE_CAPSULE_HEIGHT_FACTOR = 0.15                  # wysokość kapsuły (proporcja wys.)
SCORE_CAPSULE_BORDER_COLOR = (120, 200, 255, 220)   # obrys kapsuły
SCORE_CAPSULE_BG = (22, 26, 34, 170)                # tło kapsuły (z alpha)
SCORE_CAPSULE_RADIUS = 26                           # promień rogów kapsuły
SCORE_CAPSULE_SHADOW = (0, 0, 0, 140)               # cień kapsuły
SCORE_CAPSULE_SHADOW_OFFSET = (3, 5)                # offset cienia
SCORE_CAPSULE_MIN_HEIGHT_BONUS = 15                 # minimalny „dodatkowy” wzrost wysokości

# Typography (rozmiary bazowe; w kodzie są skalowane do okna)
FONT_PATH = str(PKG_DIR / "assets" / "font" / "Orbitron-VariableFont_wght.ttf")
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

# --- Modifiers (UI table) ---
MODIFIER_OPTIONS = ["—", "remap", "spin", "memory", "joystick"]  # "—" = none

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

def init_gpio(iq: InputQueue):
    if IS_WINDOWS or not GPIO_AVAILABLE:
        return {}
    pins = {"CIRCLE": PINS.CIRCLE, "CROSS": PINS.CROSS, "SQUARE": PINS.SQUARE, "TRIANGLE": PINS.TRIANGLE}
    buttons = {name: Button(pin, pull_up=GPIO_PULL_UP, bounce_time=GPIO_BOUNCE_TIME) for name, pin in pins.items()}
    for name, btn in buttons.items():
        btn.when_pressed = (lambda n=name: iq.push(n))
    return buttons

# ========= ENUMS =========

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
    hits_required: int = LEVEL_GOAL_PER_LEVEL
    control_flip_lr_ud: bool = False   
    modifiers: List[str] = field(default_factory=list)   

LEVELS: Dict[int, LevelCfg] = {
    1: LevelCfg(1,
        rules=[],
        instruction="Level 1 — Classic\nOdpowiadaj poprawnie.",
        hits_required=15
    ),
    2: LevelCfg(2,
        rules=[RuleSpec(RuleType.MAPPING, banner_on_level_start=True, periodic_every_hits=RULE_EVERY_HITS)],
        instruction="Level 2 — New Rule\nZwracaj uwagę na baner.",
        instruction_sec=5.0,
        hits_required=15
    ),
    3: LevelCfg(3,
        rules=[],
        rotations_per_level=3,
        instruction="Level 3 — Rotacje\nUkład ringu zmienia się w trakcie.",
        
        hits_required=15
    ),
    4: LevelCfg(4,
        rules=[RuleSpec(RuleType.MAPPING, banner_on_level_start=True, periodic_every_hits=RULE_EVERY_HITS)],
        rotations_per_level=3,
        instruction="Level 4 — Mix\nReguly + rotacje.",
        instruction_sec=5.0,  
        hits_required=15
    ),
    5: LevelCfg(5,
        rules=[],
        rotations_per_level=1,
        memory_mode=True, memory_intro_sec=3.0,
        instruction="Level 5 — Memory\nZapamiętaj układ, potem ikony znikną.",
        
        hits_required=15
    ),
    6: LevelCfg(6,
        rules=[],
        rotations_per_level=3,                
        memory_mode=True, memory_intro_sec=3.0,  
        instruction="Level 6 — Memory + Rotacje\nZapamiętaj układ — ring będzie się obracał.",
        instruction_sec=5.0,
        hits_required=15
    ),
    7: LevelCfg(7,
        rules=[],                              
        rotations_per_level=0,
        memory_mode=False,
        control_flip_lr_ud=True,               
        instruction="Level 7 — Odwrócone sterowanie\nLewo↔Prawo oraz Góra↔Dół są zamienione.",
        instruction_sec=5.0,
        hits_required=15
    ),
}

def apply_levels_from_cfg(cfg: dict) -> None:
    lvl_cfg = cfg.get("levels", {}) or {}
    for k, v in lvl_cfg.items():
        try:
            lid = int(k)
            if lid in LEVELS and isinstance(v, dict):
                L = LEVELS[lid]
                if "hits" in v:
                    L.hits_required = int(max(1, min(999, v["hits"])))
                if "color" in v and isinstance(v["color"], (list, tuple)) and len(v["color"]) == 3:
                    r,g,b = [int(max(0, min(255, c))) for c in v["color"]]
                    L.score_color = (r,g,b)
                if "mods" in v and isinstance(v["mods"], list):
                    mods = [m if m in MODIFIER_OPTIONS else "—" for m in v["mods"]]
                    while len(mods) < 3: mods.append("—")
                    L.modifiers = mods[:3]
        except Exception:
            pass

apply_levels_from_cfg(CFG)

def _ensure_level_exists(lid: int) -> None:
    if lid in LEVELS:
        return
    LEVELS[lid] = LevelCfg(
        id=lid,
        rules=[],
        rotations_per_level=0,
        memory_mode=False,
        instruction=f"Level {lid}",
        hits_required=LEVEL_GOAL_PER_LEVEL,
        modifiers=_derive_mods_from_fields(LevelCfg(lid))  # wstępne „— — —”
    )


def _derive_mods_from_fields(L: LevelCfg) -> List[str]:
    mods = []
    if any(s.type is RuleType.MAPPING for s in (L.rules or [])): mods.append("remap")
    if getattr(L, "rotations_per_level", 0) > 0:                 mods.append("spin")
    if getattr(L, "memory_mode", False):                         mods.append("memory")
    if getattr(L, "control_flip_lr_ud", False):                  mods.append("joystick")
    if not mods: mods = ["—"]
    while len(mods) < 3: mods.append("—")
    return mods[:3]

for L in LEVELS.values():
    if not getattr(L, "modifiers", None):
        L.modifiers = _derive_mods_from_fields(L)

# ========= TUTORIAL =========
@dataclass
class DemoItem:
    at: float                     # kiedy zacząć (od startu tutorialu)
    symbol: str                   # jaki symbol pojawia się w centrum
    slide_delay: float = 1.0      # po ilu sekundach od pojawienia się rusza w stronę ringu
    slide_duration: float = 0.55  # jak długo „wyjeżdża” (wolniej niż gameplay EXIT_SLIDE_SEC)
    use_mapping: bool = False     # jeśli True i jest mapping A⇒B, to jadę do B (gdy symbol==A); w innych przypadkach jadę „do siebie”
    rotate_ring: bool = False     # jeśli True – wykonaj losową rotację layoutu ringu tuż PRZED startem itemu (tylko wizualnie)
    tail_sec: float = 0.20        # chwila, aby symbol "doszedł" i zniknął estetycznie

class TutorialPlayer:
    def __init__(self, game: 'Game', items: list[DemoItem], *,
                 caption: str = "",
                 mapping_pair: Optional[tuple[str,str]] = None,
                 show_mapping_banner: bool = False,
                 sequential: bool = True,
                 seq_gap: float = 0.12,
                 static_banner: bool = True):  
         
        self.g = game
        self.caption = caption
        self.show_caption = True   

        # niezależny czas tutorialu
        self.t0 = game.now()

        # własna kopia układu ringu (nie ruszamy stanu gry)
        self.ring_layout: dict[str,str] = dict(game.ring_layout)

        # sekwencja
        self.items = sorted(items, key=lambda it: it.at)
        self._spawned_idx: int = -1      
        self._active: list[dict] = []
        self._finished = False

        # mapping & baner
        self.mapping_pair = mapping_pair  # np. ('CIRCLE','TRIANGLE')
        self.show_mapping_banner = bool(show_mapping_banner)
        self.static_banner = bool(static_banner)
        self.banner_start_t = self.g.now() if show_mapping_banner and mapping_pair else None

        # sterowanie sekwencją
        self.sequential = bool(sequential)
        self.seq_gap = float(seq_gap)
        self._next_ready_at = self.t0  

    # --- pomocnicze ---
    def _pos_for_symbol(self, sym: str) -> str:
        return next(p for p, s in self.ring_layout.items() if s == sym)

    def _target_for(self, sym: str, use_mapping: bool) -> str:
        if use_mapping and self.mapping_pair and sym == self.mapping_pair[0]:
            return self._pos_for_symbol(self.mapping_pair[1])
        return self._pos_for_symbol(sym)

    # --- fazy ---
    def update(self):
        now = self.g.now()
        t = now - self.t0

        # 1) update aktywnych
        still = []
        before = bool(self._active)

        for inst in self._active:
            it: DemoItem = inst['item']
            started: float = inst['started']
            slide_start = inst['slide_start']

            # start slajdu po opóźnieniu
            if slide_start is None and (now - started) >= max(0.0, it.slide_delay):
                inst['slide_start'] = now
                slide_start = now

            # całkowite „życie” instancji: delay + duration + tail
            life = it.slide_delay + it.slide_duration + it.tail_sec
            alive = (now - started) <= life

            if alive:
                still.append(inst)
            else:
                # dopiero co się skończyła ta scenka
                if it.rotate_ring and not inst.get('rot_scheduled', False):
                    # odpal animację obrotu ringu (bez glitcha), poczekaj na nią
                    rot_dur = 0.8
                    self.g.start_ring_rotation(dur=rot_dur, spins=2.0, swap_at=0.5)
                    inst['rot_scheduled'] = True
                    # następna scenka najwcześniej po rotacji + mały oddech sekwencyjny
                    self._next_ready_at = now + rot_dur + self.seq_gap

        self._active = [i for i in still if not i.get('rot_scheduled', False)]
        if before and not self._active:
            # jeśli nic nie ustawiło _next_ready_at (np. brak rotacji) – daj zwykły oddech
            self._next_ready_at = max(self._next_ready_at, now + self.seq_gap)

        # 2) sekwencyjne spawnowanie następnych (dopiero gdy nic nie jest aktywne i minął _next_ready_at)
        if self.sequential:
            if not self._active and (self._spawned_idx + 1) < len(self.items):
                nxt = self.items[self._spawned_idx + 1]
                if t >= max(nxt.at, 0.0) and now >= self._next_ready_at:
                    self._spawned_idx += 1
                    it = self.items[self._spawned_idx]
                    # UWAGA: już NIE rotujemy tutaj – rotacja jest po zakończeniu poprzedniej scenki
                    self._active.append({'item': it, 'started': now, 'slide_start': None})
        else:
            # tryb równoległy – bez zmian, ale też bez rotacji przed spawnem
            while (self._spawned_idx + 1) < len(self.items) and self.items[self._spawned_idx + 1].at <= t:
                self._spawned_idx += 1
                it = self.items[self._spawned_idx]
                self._active.append({'item': it, 'started': now, 'slide_start': None})

        # 3) koniec tutorialu
        if (self._spawned_idx + 1) >= len(self.items) and not self._active:
            self._finished = True

    def is_finished(self) -> bool:
        return bool(self._finished)

    # --- render ---
    def _draw_mapping_banner(self):
        if not (self.mapping_pair and self.show_mapping_banner and self.banner_start_t is not None):
            return

        g = self.g

        # Tryb statyczny – używany na ekranie instrukcji (preferowany dla L2/L4)
        if self.static_banner:
            # pozycjonowanie nad ringiem
            base_size = int(g.w * SYMBOL_BASE_SIZE_FACTOR)
            cx, cy = int(g.w * 0.5), int(g.h * CENTER_Y_FACTOR)
            r = int(base_size * RING_RADIUS_FACTOR)

            panel_scale = RULE_BANNER_PIN_SCALE * g.fx.pulse_scale('banner')
            symbol_scale = RULE_SYMBOL_SCALE_PINNED
            panel, shadow = g._render_rule_panel_surface(
                self.mapping_pair, panel_scale, symbol_scale, label_font=g.rule_font_pinned
            )
            pw, ph = panel.get_size()

            px = (g.w - pw) // 2
            # umieść tuż nad ringiem, z małym marginesem
            margin = g.px(12)                  # odstęp od ringa
            lift   = int(g.h * 0.06)           # podniesienie ~6% wysokości ekranu (wyżej = większa wartość)
            safe_top = int(g.h * 0.18)         # nie wchodź w nagłówek "LEVEL X"

            py = cy - r - ph - margin - lift   # podnieś baner
            py = max(safe_top, py)             # clamp, żeby nie przyklejać do tytułu

            g.screen.blit(shadow, (px + 3, py + 5))
            g.screen.blit(panel, (px, py))
            return

        # --- Tryb animowany (stary) ---
        now = g.now()
        t = now - self.banner_start_t
        IN, HOLD, OUT = RULE_BANNER_IN_SEC, RULE_BANNER_HOLD_SEC, RULE_BANNER_TO_TOP_SEC
        total = IN + HOLD + OUT
        if t > total:
            panel, shadow = g._render_rule_panel_surface(self.mapping_pair, RULE_BANNER_PIN_SCALE,
                                                        RULE_SYMBOL_SCALE_PINNED, label_font=g.rule_font_pinned)
            pw, ph = panel.get_size()
            px = (g.w - pw)//2
            py = int(getattr(g, "_rule_pinned_y", g.topbar_rect.bottom + g.px(12)))
            g.screen.blit(shadow, (px+3, py+5))
            g.screen.blit(panel, (px, py))
            return

        if t <= IN:
            p = g._ease_out_cubic(t / max(1e-6, IN))
            panel_scale = RULE_BANNER_PIN_SCALE + (1.0 - RULE_BANNER_PIN_SCALE) * p
            symbol_scale = RULE_SYMBOL_SCALE_PINNED + (RULE_SYMBOL_SCALE_CENTER - RULE_SYMBOL_SCALE_PINNED) * p
            start_y = -int(g.h * 0.35)
            mid_y = int(g.h * 0.30)
            y = int(start_y + (mid_y - start_y) * p)
            font = g.rule_font_center
        elif t <= IN + HOLD:
            panel_scale = 1.0; symbol_scale = RULE_SYMBOL_SCALE_CENTER
            mid_y = int(g.h * 0.30); y = mid_y
            font = g.rule_font_center
        else:
            p = g._ease_out_cubic((t - IN - HOLD) / max(1e-6, OUT))
            panel_scale = 1.0 + (RULE_BANNER_PIN_SCALE - 1.0) * p
            symbol_scale = RULE_SYMBOL_SCALE_CENTER + (RULE_SYMBOL_SCALE_PINNED - RULE_SYMBOL_SCALE_CENTER) * p
            mid_y = int(g.h * 0.30)
            pinned_y = int(getattr(g, "_rule_pinned_y", g.topbar_rect.bottom + g.px(12)))
            y = int(mid_y + (pinned_y - mid_y) * p)
            font = g.rule_font_pinned

        panel, shadow = g._render_rule_panel_surface(self.mapping_pair, panel_scale, symbol_scale, label_font=font)
        pw, ph = panel.get_size()
        px = (g.w - pw)//2
        g.screen.blit(shadow, (px+3, y+5))
        g.screen.blit(panel, (px, y))

    def draw(self):
        g = self.g
        g._blit_bg()

        base_size = int(g.w * SYMBOL_BASE_SIZE_FACTOR)
        cx, cy = int(g.w * 0.5), int(g.h * CENTER_Y_FACTOR)

        # OBRÓT RINGU PODCZAS INSTRUKCJI
        spin_deg = g._update_ring_rotation_anim()

        # ring z aktualnym układem tutorialowym + obrotem
        g.ring.draw((cx, cy), base_size, layout=self.ring_layout, spin_deg=spin_deg)

        # baner
        self._draw_mapping_banner() 

        # aktywne instancje
        for inst in self._active:
            it: DemoItem = inst['item']
            started: float = inst['started']
            slide_start = inst['slide_start']

            target_pos = self._target_for(it.symbol, it.use_mapping)

            if slide_start is None:
                rect = pygame.Rect(0, 0, base_size, base_size); rect.center = (cx, cy)
                g.draw_symbol(g.screen, it.symbol, rect)
            else:
                prog = (g.now() - slide_start) / max(1e-6, it.slide_duration)
                prog = 0.0 if prog < 0 else 1.0 if prog > 1 else prog
                eased = g._ease_out_cubic(prog)

                r = int(base_size * RING_RADIUS_FACTOR)
                pos_xy = {"TOP":(cx,cy-r), "RIGHT":(cx+r,cy), "LEFT":(cx-r,cy), "BOTTOM":(cx,cy+r)}
                tx, ty = pos_xy[target_pos]
                ex = int(cx + (tx - cx) * 1.2 * eased)
                ey = int(cy + (ty - cy) * 1.2 * eased)

                scale = (1.0 - 0.25 * eased)
                size = max(1, int(g.w * SYMBOL_BASE_SIZE_FACTOR * scale))
                srf = pygame.Surface((size, size), pygame.SRCALPHA)
                g.draw_symbol(srf, it.symbol, srf.get_rect())

                # fade jak w gameplay exit-slide: gaśnie w trakcie slajdu
                if prog < 1.0:
                    alpha = max(0, int(255 * (1.0 - eased)))
                else:
                    alpha = 0
                srf.set_alpha(alpha)

                if alpha > 0:
                    g.screen.blit(srf, (ex - size//2, ey - size//2))

            if self.caption and self.show_caption:
                r = int(base_size * RING_RADIUS_FACTOR)
                margin = g.px(14)
                y = cy - r - g.mid.get_height() - margin
                if getattr(self, "static_banner", False):
                    y -= g.px(12)
                tw, th = g.mid.size(self.caption)
                g.draw_text(self.caption, pos=(g.w/2 - tw/2, y), font=g.mid, color=ACCENT)

def build_tutorial_for_level(g: 'Game') -> Optional['TutorialPlayer']:
    """Buduje tutorial na podstawie *aktualnej* konfiguracji levelu (modyfikatorów)."""
    L = g.level_cfg

    # Aktywne „cechy” poziomu
    has_remap   = any(s.type is RuleType.MAPPING for s in (L.rules or []))
    has_rotate  = getattr(L, "rotations_per_level", 0) > 0
    has_memory  = bool(getattr(L, "memory_mode", False))
    has_invert  = bool(getattr(L, "control_flip_lr_ud", False))

    # Podpis pod tytułem – złożony z aktywnych cech (np. "Remap + rotate")
    parts = []
    if has_remap:  parts.append("Remap")
    if has_rotate: parts.append("Rotate")
    if has_memory: parts.append("Memory")
    if has_invert: parts.append("Controls flipped")
    caption = " + ".join(parts) if parts else "Classic"

    # Helper do losowania symboli
    def SYM(exclude: set[str] = set()) -> str:
        import random
        choices = [s for s in SYMS if s not in exclude]
        return random.choice(choices) if choices else random.choice(SYMS)

    items: list[DemoItem] = []
    mapping_pair: Optional[tuple[str, str]] = None

    # Jeżeli jest remap – pokaż baner i 2× symbol A kierowany do B + 1 neutralny
    if has_remap:
        a = SYM()
        b = SYM({a})
        mapping_pair = (a, b)
        neutral = SYM({a, b})
        items += [
            DemoItem(at=0.0, symbol=a,       slide_delay=1.0, slide_duration=0.60, use_mapping=True,  rotate_ring=False),
            DemoItem(at=0.0, symbol=neutral, slide_delay=1.0, slide_duration=0.60, use_mapping=False, rotate_ring=False),
            DemoItem(at=0.0, symbol=a,       slide_delay=1.0, slide_duration=0.60, use_mapping=True,  rotate_ring=False),
        ]
    else:
        # Bez remapu – trzy różne symbole do „siebie”
        x = SYM(); y = SYM({x}); z = SYM({x, y})
        items += [
            DemoItem(at=0.0, symbol=x, slide_delay=1.0, slide_duration=0.60),
            DemoItem(at=0.0, symbol=y, slide_delay=1.0, slide_duration=0.60),
            DemoItem(at=0.0, symbol=z, slide_delay=1.0, slide_duration=0.60),
        ]

    # Jeżeli są rotacje – zaznacz obrót przy pierwszych dwóch scenkach (dokładnie jak w Twoim starym L3/L4)
    if has_rotate and len(items) >= 2:
        items[0].rotate_ring = True
        items[1].rotate_ring = True

    # Memory: samo wyświetlenie captionu wystarcza (mechanika chowania ikon już jest w kodzie gry).
    # Invert: dopisaliśmy do captionu, sterowanie działa z pól levelu.

    # Baner remapu pokazujemy jako statyczny (czytelny na ekranie instrukcji)
    return TutorialPlayer(
        g, items,
        caption=caption,
        mapping_pair=mapping_pair,
        show_mapping_banner=bool(mapping_pair),
        static_banner=True,     # przypięty, bez animacji IN/HOLD/OUT
        sequential=True,
        seq_gap=0.12,
    )

# ========= RULE MANAGER =========
class RuleManager:
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
        self._pulses = { 'symbol': (0.0, 0.0), 'streak': (0.0, 0.0), 'banner': (0.0, 0.0), 'score': (0.0, 0.0), 'timer': (0.0, 0.0) }
        self._ring_pulses: dict[str, tuple[float, float]] = {}

        # exit slide (po poprawnej odpowiedzi)
        self.exit_active = False
        self.exit_start = 0.0
        self.exit_symbol: Optional[str] = None
        self.exit_duration = EXIT_SLIDE_SEC

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

    def trigger_pulse(self, kind: str, duration: float | None = None):
        if kind not in self._pulses:
            return
        dur = float(duration if duration is not None else PULSE_KIND_DURATION.get(kind, PULSE_BASE_DURATION))
        now = self.now()
        self._pulses[kind] = (now, now + max(1e-3, dur))

    def trigger_pulse_symbol(self): self.trigger_pulse('symbol')
    def trigger_pulse_streak(self): self.trigger_pulse('streak')
    def trigger_pulse_banner(self): self.trigger_pulse('banner')

        # --- Ring icon pulse (per pozycja) ---
    def trigger_pulse_ring(self, key: str, duration: float | None = None):
        if not key:
            return
        dur = float(duration if duration is not None else PULSE_KIND_DURATION.get('streak', PULSE_BASE_DURATION))
        now = self.now()
        self._ring_pulses[key] = (now, now + max(1e-3, dur))

    def ring_pulse_scale(self, key: str) -> float:
        st, en = self._ring_pulses.get(key, (0.0, 0.0))
        if st <= 0.0 or self.now() >= en:
            return 1.0
        dur = max(1e-6, en - st)
        t = (self.now() - st) / dur
        # delikatny, czytelny pulse
        local_max = 1.14  # ~+14% skali
        return 1.0 + (local_max - 1.0) * math.sin(math.pi * max(0.0, min(1.0, t)))

    # -------- queries / math --------
    def _pulse_curve01(self, t: float, kind: str) -> float:
        import math
        t = max(0.0, min(1.0, t))
        # skala = baza * mnożnik kind
        kscale = float(PULSE_KIND_SCALE.get(kind, 1.0))
        max_scale = float(PULSE_BASE_MAX_SCALE) * kscale
        return 1.0 + (max_scale - 1.0) * math.sin(math.pi * t)

    def pulse_scale(self, kind: str) -> float:
        start, until = self._pulses.get(kind, (0.0, 0.0))
        if start <= 0.0:
            return 1.0
        now = self.now()
        if now >= until:
            return 1.0
        dur = max(1e-6, until - start)
        t = (now - start) / dur
        return self._pulse_curve01(t, kind)
    
    def is_pulse_active(self, kind: str) -> bool:
        start, until = self._pulses.get(kind, (0.0, 0.0))
        return start > 0.0 and self.now() < until

    def stop_pulse(self, kind: str):
        if kind in self._pulses:
            self._pulses[kind] = (0.0, 0.0)

    def trigger_pulse_score(self): self.trigger_pulse('score')

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

    def start_exit_slide(self, symbol: str, duration: float = EXIT_SLIDE_SEC):
        self.exit_symbol = symbol
        self.exit_duration = max(0.05, float(duration))
        self.exit_start = self.now()
        self.exit_active = True

    def is_exit_active(self) -> bool:
        return self.exit_active and (self.now() - self.exit_start) <= self.exit_duration

    def exit_progress(self) -> float:
        if not self.exit_active:
            return 0.0
        t = (self.now() - self.exit_start) / max(1e-6, self.exit_duration)
        return max(0.0, min(1.0, t))

    def clear_exit(self):
        self.exit_active = False
        self.exit_symbol = None
        self.exit_start = 0.0

# ========= SYMBOL MODEL =========
@dataclass(frozen=True)
class Symbol:
    name: str
    color: Tuple[int, int, int]
    image_cfg_key: str  # klucz w CFG["images"], np. "symbol_circle"

    def draw(self, surface: pygame.Surface, rect: pygame.Rect, *, images: ImageStore, cfg: dict) -> None:
        # spróbuj wczytać PNG z configu, a potem fallback wektorowy
        path = cfg.get("images", {}).get(self.image_cfg_key)
        img = images.load(path) if path else None
        if img:
            iw, ih = img.get_size()
            scale = min(rect.width / iw, rect.height / ih)
            new_size = (int(iw * scale), int(ih * scale))
            scaled = pygame.transform.smoothscale(img, new_size)
            r = scaled.get_rect(center=rect.center)
            surface.blit(scaled, r)
            return

        # ---- fallback: rysunek wektorowy spójny z dotychczasowym ----
        color = self.color
        thickness = SYMBOL_DRAW_THICKNESS
        cx, cy = rect.center
        w, h = rect.size
        r = min(w, h) * SYMBOL_CIRCLE_RADIUS_FACTOR

        if self.name == "CIRCLE":
            pygame.draw.circle(surface, color, (int(cx), int(cy)), int(r), thickness)

        elif self.name == "SQUARE":
            side = r * 1.6
            rr = pygame.Rect(0, 0, side, side)
            rr.center = rect.center
            pygame.draw.rect(surface, color, rr, thickness, border_radius=SYMBOL_SQUARE_RADIUS)

        elif self.name == "TRIANGLE":
            a = (cx, cy - r)
            b = (cx - r * SYMBOL_TRIANGLE_POINT_FACTOR, cy + r * SYMBOL_TRIANGLE_POINT_FACTOR)
            c = (cx + r * SYMBOL_TRIANGLE_POINT_FACTOR, cy + r * SYMBOL_TRIANGLE_POINT_FACTOR)
            pygame.draw.polygon(surface, color, [a, b, c], thickness)

        elif self.name == "CROSS":
            k = r * SYMBOL_CROSS_K_FACTOR
            pygame.draw.line(surface, color, (cx - k, cy - k), (cx + k, cy + k), thickness)
            pygame.draw.line(surface, color, (cx - k, cy + k), (cx + k, cy - k), thickness)

SYMBOLS: Dict[str, Symbol] = {
    "TRIANGLE": Symbol("TRIANGLE", SYMBOL_COLORS["TRIANGLE"], "symbol_triangle"),
    "CIRCLE":   Symbol("CIRCLE",   SYMBOL_COLORS["CIRCLE"],   "symbol_circle"),
    "SQUARE":   Symbol("SQUARE",   SYMBOL_COLORS["SQUARE"],   "symbol_square"),
    "CROSS":    Symbol("CROSS",    SYMBOL_COLORS["CROSS"],    "symbol_cross"),
}

SYMS: List[str] = list(SYMBOLS.keys())

# ========= RING =========
class InputRing:
    def __init__(self, game: 'Game'):
        self.g = game

    def draw(self, center: tuple[int,int], base_size: int, *, layout: Optional[dict[str,str]] = None, spin_deg: float = 0.0) -> None:
        g = self.g
        cx, cy = center
        r = int(base_size * RING_RADIUS_FACTOR)

        base, hi, soft = g.ring_colors()

        # time for rotation
        t = g.now() - getattr(g, "_ring_anim_start", g.now())
        # positive degrees in pygame are CCW, so keep this positive for CCW
        base_ccw = 60 + 8 * (g.level - 1)
        rot_ccw_deg = t * base_ccw

        # canvas for ring + icons
        margin = 36
        side = (r + margin) * 2
        C = side // 2
        out = pygame.Surface((side, side), pygame.SRCALPHA)

        def blit_to_out(surf):
            out.blit(surf, surf.get_rect(center=(C, C)))

        # --- Try PNG ring first ---
        ring_path = g.cfg.get("images", {}).get("ring")
        ring_img = g.images.load(ring_path) if ring_path else None

        if ring_img:
            # scale ring to fit comfortably inside the canvas
            iw, ih = ring_img.get_size()
            # leave a tiny padding so strokes aren’t clipped
            max_target = int(side * 0.94)
            scale = min(max_target / max(1, iw), max_target / max(1, ih))
            ring_scaled = pygame.transform.smoothscale(ring_img, (int(iw * scale), int(ih * scale)))

            # rotate CCW by rot_ccw_deg
            ring_rot = pygame.transform.rotozoom(ring_scaled, rot_ccw_deg, 1.0)
            blit_to_out(ring_rot)
        else:
            # --- Fallback to your procedural multi-layer ring ---
            # keep your original layers so nothing regresses if PNG is missing
            base_cw  = 40 + 6 * (g.level - 1)
            rot_cw_deg  = -t * base_cw    # CW (negative), to keep the layered contrast
            rot_ccw_deg2 = rot_ccw_deg    # CCW

            def new_layer():
                return pygame.Surface((side, side), pygame.SRCALPHA)

            layers = []
            # L1
            l1a = new_layer()
            self._arc(l1a, C, r, 0.75, max(2, RING_THICKNESS+1), (*base, RING_ALPHA_MAIN), start=-math.pi*0.5)
            l1a = pygame.transform.rotozoom(l1a, rot_ccw_deg2, 1.0)

            l1b = new_layer()
            self._arc(l1b, C, int(r*1.08), 0.60, 3, (*soft, RING_ALPHA_SOFT), start=0.0)
            l1b = pygame.transform.rotozoom(l1b, rot_cw_deg, 1.0)
            layers += [l1a, l1b]

            if g.level >= 2:
                l2a = new_layer()
                self._ticks(l2a, C, r, 48, long_every=4, color=(*soft, RING_ALPHA_TICKS))
                l2a = pygame.transform.rotozoom(l2a, rot_cw_deg*1.15, 1.0)

                l2b = new_layer()
                self._dashed_ring(l2b, C, int(r*0.82), dash_deg=10, gap_deg=7, width=2, alpha=RING_ALPHA_SOFT, color=soft)
                l2b = pygame.transform.rotozoom(l2b, rot_ccw_deg2*1.1, 1.0)
                layers += [l2a, l2b]

            if g.level >= 3:
                l3 = new_layer()
                sweep = math.radians(42)
                start = t * 1.2
                rect = pygame.Rect(0, 0, int(r*0.92*2), int(r*0.92*2)); rect.center = (C, C)
                pygame.draw.arc(l3, (*hi, RING_ALPHA_HI), rect, start, start + sweep, 7)
                for w, a in ((12, 60), (20, 35)):
                    pygame.draw.arc(l3, (*hi, a), rect.inflate(w, w), start, start + sweep, 8)
                layers.append(l3)

            if g.level >= 4:
                l4 = new_layer()
                orbit_r = int(r * 1.15)
                for k in range(3):
                    ang = t * 1.4 + k * (2*math.pi/3)
                    x = int(C + math.cos(ang) * orbit_r)
                    y = int(C + math.sin(ang) * orbit_r)
                    pygame.draw.circle(l4, (*base, 170), (x, y), 3)
                layers.append(l4)

            if g.level >= 5:
                l5 = new_layer()
                self._dashed_ring(l5, C, int(r*1.20), dash_deg=16, gap_deg=10, width=3, alpha=150, color=base)
                l5 = pygame.transform.rotozoom(l5, rot_cw_deg*0.8, 1.0)
                layers.append(l5)

            for L in layers:
                blit_to_out(L)

        # --- Icons on the ring (same as before) ---
        if not (g.level_cfg.memory_mode and not g.memory_show_icons):
            icon_size = int(base_size * RING_ICON_SIZE_FACTOR)
            pos_xy = {"TOP": (cx, cy - r), "RIGHT": (cx + r, cy), "LEFT": (cx - r, cy), "BOTTOM": (cx, cy + r)}
            active_layout = layout if layout is not None else g.ring_layout
            for pos, (ix, iy) in pos_xy.items():
                name = active_layout.get(pos, DEFAULT_RING_LAYOUT[pos])
                scale = self.g.fx.ring_pulse_scale(pos)
                size  = max(1, int(icon_size * scale))
                rect  = pygame.Rect(0, 0, size, size)

                # map to 'out' surface space
                ox = C + (ix - cx)
                oy = C + (iy - cy)
                rect.center = (ox, oy)

                self.g.draw_symbol(out, name, rect)


        # apply additional gameplay rotation (layout transition) if any
        if abs(spin_deg) > 0.0001:
            out = pygame.transform.rotozoom(out, spin_deg, 1.0)

        self.g.screen.blit(out, out.get_rect(center=(cx, cy)))

# ========= TIMEBAR =========
class TimeBar:
    def __init__(self, game: 'Game'):
        self.g = game

    def draw(self, ratio: float, label: Optional[str] = None) -> None:
        g = self.g
        ratio = max(0.0, min(1.0, ratio))
        if ratio <= TIMER_BAR_CRIT_TIME:   fill_color = TIMER_BAR_CRIT_COLOR
        elif ratio <= TIMER_BAR_WARN_TIME: fill_color = TIMER_BAR_WARN_COLOR
        else:                              fill_color = TIMER_BAR_FILL

        # PULSE WYSOKOŚCI PASKA
        pulse_scale = g.fx.pulse_scale('timer')
        bar_w = int(g.w * TIMER_BAR_WIDTH_FACTOR)
        base_h = int(TIMER_BAR_HEIGHT)
        bar_h = max(1, int(base_h * pulse_scale))
        bar_x = (g.w - bar_w) // 2
        bottom_margin = int(g.h * TIMER_BOTTOM_MARGIN_FACTOR)
        bar_y = g.h - bottom_margin - bar_h

        # tło
        pygame.draw.rect(g.screen, TIMER_BAR_BG, (bar_x, bar_y, bar_w, bar_h), border_radius=TIMER_BAR_BORDER_RADIUS)      

        # wypełnienie
        fill_w = int(bar_w * ratio)
        if fill_w > 0:
            pygame.draw.rect(g.screen, fill_color, (bar_x, bar_y, fill_w, bar_h), border_radius=TIMER_BAR_BORDER_RADIUS)

        # ramka
        pygame.draw.rect(g.screen, TIMER_BAR_BORDER, (bar_x, bar_y, bar_w, bar_h), width=TIMER_BAR_BORDER_W, border_radius=TIMER_BAR_BORDER_RADIUS)

        # pionowy znacznik
        indicator_x = max(bar_x, min(bar_x + bar_w, bar_x + fill_w))
        indicator_rect = pygame.Rect(
            indicator_x - TIMER_POSITION_INDICATOR_W // 2,
            bar_y - TIMER_POSITION_INDICATOR_PAD,
            TIMER_POSITION_INDICATOR_W,
            bar_h + TIMER_POSITION_INDICATOR_PAD * 2,
        )
        pygame.draw.rect(g.screen, ACCENT, indicator_rect)

        # podpis nad paskiem
        if label:
            timer_font = getattr(g, "timer_font", g.mid)
            t = g.draw_text(label, color=TIMER_BAR_TEXT_COLOR, font=timer_font, shadow=True, glitch=False)
            tx = bar_x + (bar_w - t.get_width()) // 2
            ty = bar_y - t.get_height() - TIMER_LABEL_GAP
            g.screen.blit(t, (tx, ty))

# ========= GAME =========
class Game:

    # ---- Inicjalizacja i podstawy cyklu życia ----

    def __init__(self, screen: pygame.Surface, mode: Mode = Mode.SPEEDUP):
        self.screen = screen
        self.cfg = CFG
        self.images = IMAGES
        self.mode: Mode = mode
        self.scene: Scene = Scene.MENU
        self.tutorial: Optional[TutorialPlayer] = None

        self.w, self.h = self.screen.get_size()
        self.clock = pygame.time.Clock()

        # --- window ---
        self.last_windowed_size = tuple(CFG.get("display", {}).get("windowed_size", WINDOWED_DEFAULT_SIZE))
        self.last_window_size = self.screen.get_size()

        # --- key delay / debouncing for keyboard ---
        self.keys_down: set[int] = set()
        self.lock_until_all_released = False
        self.accept_after = 0.0

        # --- fonts ---
        self.hud_label_font = pygame.font.Font(FONT_PATH, HUD_LABEL_FONT_SIZE)
        self.hud_value_font = pygame.font.Font(FONT_PATH, HUD_VALUE_FONT_SIZE)
        self._font_cache: dict[tuple[str,int,bool,bool], pygame.font.Font] = {}
        self._sysfont_fallback = "arial"

        # background
        self.bg_img_raw = self._load_background()
        self.bg_img: Optional[pygame.Surface] = None

        # layout & framebuffer
        self._recompute_layout()
        self.fb = pygame.Surface((self.w, self.h), pygame.SRCALPHA)

        # fonts for rule banner stages (center vs pinned) – ustawi je _rebuild_fonts()
        self.rule_font_center: Optional[pygame.font.Font] = None
        self.rule_font_pinned: Optional[pygame.font.Font] = None
        self.ui_scale = 1.0
        self._rebuild_fonts() 

        # gameplay state
        self.level = 1
        self.hits_in_level = 0
        self.level_goal = LEVEL_GOAL_PER_LEVEL
        self.levels_active = LEVELS_ACTIVE_FOR_NOW

        self.score = 0
        self.streak = 0
        self.best_streak = 0 
        self.final_total = 0
        self.lives = MAX_LIVES

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

        # --- renderers ---
        self.ring = InputRing(self)
        self.timebar = TimeBar(self)

        # --- rule / banner manager ---
        self.rules = RuleManager()
        self.banner = BannerManager(RULE_BANNER_IN_SEC, RULE_BANNER_HOLD_SEC, RULE_BANNER_TO_TOP_SEC)

        # ring
        self.ring_layout = dict(DEFAULT_RING_LAYOUT)
        self._ring_anim_start = self.now()

        # --- ring rotation anim state ---
        self.rot_anim = {
            "active": False,
            "t0": 0.0,
            "dur": 0.8,          # czas animacji
            "spins": 2.0,        # ile pełnych obrotów (2 = 720°)
            "swap_at": 0.5,      # kiedy podmienić layout (ułamek czasu 0..1)
            "swapped": False,
            "from_layout": dict(self.ring_layout),
            "to_layout": dict(self.ring_layout),
}
        
        # memory (L5)
        self.memory_show_icons = True
        # (stare – nie użyjemy już do ukrywania)
        self.memory_hide_deadline = 0.0 # nowy: kiedy najpóźniej ukryć ikony (czasowo)
        self.memory_moves_count = 0     # nowy: ile ruchów wykonano zanim znikną
        self.memory_preview_armed = False   # czekaj na „sygnał” (np. koniec bannera), by wystartować odliczanie
        self._banner_was_active = False     # detekcja zbocza: koniec animacji bannera

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

        # settings buffer (Settings scene)
        self.settings_scroll = 0.0
        self._settings_row_tops: List[Tuple[float, float]] = []  # (y, height) bez scrolla
        self.settings_idx = 0
        self.settings = make_runtime_settings(CFG)

        self.settings_focus_table = False
        self.level_table_sel_row = 1          
        self.level_table_sel_col = 1          

        # effects
        self.fx = EffectsManager(self.now, glitch_enabled=self.settings.get("glitch_enabled", True))
        self.exit_dir_pos: Optional[str] = None  # "TOP"|"RIGHT"|"LEFT"|"BOTTOM"
        self.instruction_intro_t = 0.0
        self.instruction_intro_dur = 0.0

        # music
        self.music_ok = False
        self._ensure_music()

        # --- SFX ---
        self.sfx = {}
        try:
            self.sfx["point"]  = pygame.mixer.Sound("assets/sfx/sfx_point.wav")
            self.sfx["wrong"]  = pygame.mixer.Sound("assets/sfx/sfx_wrong.wav")
            self.sfx["glitch"] = pygame.mixer.Sound("assets/sfx/sfx_glitch.wav")

            # USTAWIENIE GŁOŚNOŚCI SFX (to o co pytasz)
            sfx_vol = float(CFG["audio"]["sfx_volume"])
            for s in self.sfx.values():
                s.set_volume(sfx_vol)
        except Exception:
            self.sfx = {}

        self.last_window_size = self.screen.get_size()

    def start_game(self) -> None:
        self.reset_game_state()
        self._ensure_music()
        if self.music_ok:
            pygame.mixer.music.play(-1)

    def end_game(self) -> None:
        self.scene = Scene.OVER

        # total = końcowy wynik (score + best_streak)
        self.final_total = int(max(0, self.score) + max(0, self.best_streak))
        if self.final_total > self.highscore:
            self.highscore = self.final_total
            CFG["highscore"] = int(self.highscore)
            save_config({"highscore": CFG["highscore"]})

        if self.music_ok:
            pygame.mixer.music.fadeout(MUSIC_FADEOUT_MS)


    # ---- Czas i proste utilsy ----

    def now(self) -> float:
        return time.time()
  
    def px(self, v: float) -> int:
        return max(1, int(round(v * getattr(self, "ui_scale", 1.0))))

    def _lock_inputs(self, delay: float = INPUT_ACCEPT_DELAY) -> None:
        self.lock_until_all_released = True
        self.accept_after = self.now() + max(0.0, delay)

    def _try_start_exit_slide(self, required_symbol: str) -> bool:
        if self.banner.is_active(self.now()):
            return False
        pos = next((p for p, s in self.ring_layout.items() if s == required_symbol), None)
        if not pos or not self.target:
            return False

        now = self.now()
        self.exit_dir_pos = pos
        self.fx.start_exit_slide(self.target, duration=EXIT_SLIDE_SEC)

        # pauza gry na czas zjazdu
        self.pause_start = now
        self.pause_until = max(self.pause_until, now + EXIT_SLIDE_SEC)
        return True

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

    def _memory_start_preview(self, *, reset_moves: bool = True, force_unhide: bool = False) -> None:
        if not self.level_cfg.memory_mode:
            return
        if force_unhide:
            self.memory_show_icons = True
        if reset_moves:
            self.memory_moves_count = 0
        self.memory_hide_deadline = self.now() + float(MEMORY_HIDE_AFTER_SEC)
        self.memory_preview_armed = False

# ---- Zasoby, layout, UI scale, fonty, tło ----

    def _compute_ui_scale(self) -> float:
        ref_w, ref_h = 720, 1280
        sx = self.w / ref_w
        sy = self.h / ref_h
        s = min(sx, sy)
        return max(0.6, min(2.2, s))  # clamp

    def _load_font_file(self, size: int, *, bold: bool = False, italic: bool = False) -> pygame.font.Font:
        path = FONT_PATH
        try:
            if path and os.path.exists(path):
                f = pygame.font.Font(path, size)
                if hasattr(f, "set_bold"):   f.set_bold(bold)
                if hasattr(f, "set_italic"): f.set_italic(italic)
                return f
            # brak pliku → systemowy fallback
            return pygame.font.SysFont(self._sysfont_fallback, size, bold=bold, italic=italic)
        except Exception:
            return pygame.font.SysFont(self._sysfont_fallback, size, bold=bold, italic=italic)

    def _font(self, px: int, *, bold: bool = False, italic: bool = False) -> pygame.font.Font:
        size = max(8, int(round(px)))
        key = (FONT_PATH, size, bool(bold), bool(italic))
        f = self._font_cache.get(key)
        if f is None:
            f = self._load_font_file(size, bold=bold, italic=italic)
            self._font_cache[key] = f
        return f

    def _rebuild_fonts(self) -> None:
        self.ui_scale = self._compute_ui_scale()
        self._font_cache.clear()

        def S(px: int) -> int:
            return max(8, int(round(px * self.ui_scale)))

        # główne fonty UI
        self.font              = self._font(S(FONT_SIZE_SMALL))
        self.mid               = self._font(S(FONT_SIZE_MID))
        self.big               = self._font(S(FONT_SIZE_BIG))
        self.timer_font        = self._font(S(TIMER_FONT_SIZE))
        self.hud_label_font    = self._font(S(HUD_LABEL_FONT_SIZE))
        self.hud_value_font    = self._font(S(HUD_VALUE_FONT_SIZE))
        self.score_label_font  = self._font(S(SCORE_LABEL_FONT_SIZE))
        self.score_value_font  = self._font(S(SCORE_VALUE_FONT_SIZE))
        self.settings_font     = self._font(S(FONT_SIZE_SETTINGS))

        # fonty banera reguły – bazują na wartościach z configu, ale też skaluje je UI
        c = S(int(RULE_BANNER_FONT_CENTER_PX))
        p = S(int(RULE_BANNER_FONT_PINNED_PX))
        self.rule_font_center = self._font(max(8, c))
        self.rule_font_pinned = self._font(max(8, p))
        self.hint_font        = self._font(max(8, int(self.font.get_height() * 0.85)))

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
        self.fb = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        self._rebuild_fonts() 

    def _ensure_music(self) -> None:
        if self.music_ok:
            return
        try:
            pygame.mixer.init()
            if os.path.exists(CFG["audio"]["music"]):
                pygame.mixer.music.load(CFG["audio"]["music"])
                pygame.mixer.music.set_volume(float(CFG["audio"]["music_volume"]))
                self.music_ok = True
        except Exception:
            self.music_ok = False

# ---- Okno/tryb wyświetlania & rozmiar ----

    def _set_windowed_size(self, width: int, height: int) -> None:
        width, height = self._snap_to_aspect(width, height)

        # jeśli rozmiar po snapie pokrywa się z aktualnym, nic nie rób
        cur_w, cur_h = self.screen.get_size()
        if (cur_w, cur_h) == (width, height):
            return

        self.screen = pygame.display.set_mode((width, height), WINDOWED_FLAGS)
        self.last_windowed_size = (width, height)
        self.last_window_size = (width, height)
        persist_windowed_size(width, height)

        self._recompute_layout()

    def _set_display_mode(self, fullscreen: bool) -> None:
        if fullscreen:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            self.last_window_size = self.screen.get_size()
            self._recompute_layout()
        else:
            w, h = getattr(self, "last_windowed_size", WINDOWED_DEFAULT_SIZE)
            self._set_windowed_size(w, h)
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

    def handle_resize(self, width: int, height: int) -> None:
        if bool(self.settings.get("fullscreen", CFG.get("display", {}).get("fullscreen", True))):
            return
        self._set_windowed_size(width, height)

# ---- Klawisze i mapowania wejść ----

    def _recompute_keymap(self) -> None:
        self.keymap_current = {
            k: self.ring_layout[self._control_pos(pos)]
            for k, pos in self.key_to_pos.items()
        }

    def _control_pos(self, pos: str) -> str:
        if getattr(self.level_cfg, "control_flip_lr_ud", False):
            flip = {"LEFT":"RIGHT", "RIGHT":"LEFT", "TOP":"BOTTOM", "BOTTOM":"TOP"}
            return flip.get(pos, pos)
        return pos

# ---- Ustawienia ----

    def settings_items(self):
        items = [
            ("Initial time", f"{self.settings['target_time_initial']:.2f}s", "target_time_initial"),
            ("Time step", f"{self.settings['target_time_step']:+.2f}s/hit", "target_time_step"),
            ("Minimum time", f"{self.settings['target_time_min']:.2f}s", "target_time_min"),
            ("Lives", f"{int(self.settings['lives'])}", "lives"),
            ("Music volume", f"{self.settings['music_volume']:.2f}", "music_volume"),
            ("SFX volume",   f"{self.settings['sfx_volume']:.2f}",   "sfx_volume"),
            ("Fullscreen", "ON" if self.settings['fullscreen'] else "OFF", "fullscreen"),
            ("Glitch", "ON" if self.settings.get('glitch_enabled', True) else "OFF", "glitch_enabled"),
            ("Ring palette", f"{self.settings['ring_palette']}", "ring_palette"),
            ("High score", f"{self.highscore}", None),
            ("Reset high score", "PRESS \u2190/\u2192", "highscore_reset"),
            ("Rule bonus", f"{self.settings['timed_rule_bonus']:.1f}s", "timed_rule_bonus"),
            ("Levels available", f"{int(self.levels_active)}", "levels_active"),
            ("", "", None),  
        ]

        return items

    def settings_move(self, delta: int) -> None:
        items = self.settings_items()
        n, idx = len(items), self.settings_idx
        for _ in range(n):
            idx = (idx + delta) % n
            if items[idx][2] is not None:
                self.settings_idx = idx
                break
        # auto-scroll to keep selected row visible
        self._ensure_selected_visible()

    def _settings_viewport(self) -> pygame.Rect:
        top = int(self.h * SETTINGS_LIST_Y_START_FACTOR)
        # miejsce na help na dole
        help_margin = self.px(SETTINGS_HELP_MARGIN_TOP)
        help_gap    = self.px(SETTINGS_HELP_GAP)
        help_h = self.font.get_height()*2 + help_margin + help_gap + self.px(8)
        height = max(50, self.h - top - help_h)
        return pygame.Rect(0, top, self.w, height)

    def _ensure_selected_visible(self) -> None:
        if not self._settings_row_tops:
            return
        vp = self._settings_viewport()
        try:
            y, h = self._settings_row_tops[self.settings_idx]
        except IndexError:
            return
        row_top = y - self.settings_scroll
        row_bot = y + h - self.settings_scroll
        if row_top < vp.top:
            self.settings_scroll = max(0.0, y - vp.top)
        elif row_bot > vp.bottom:
            self.settings_scroll = max(0.0, (y + h) - vp.bottom)

    def toggle_settings(self) -> None:
        if self.scene is Scene.SETTINGS:
            self.settings_cancel()
        elif self.scene is Scene.MENU:
            self.open_settings()

    def settings_adjust(self, delta: int) -> None:
        items = self.settings_items()
        key = items[self.settings_idx][2]

        if key is None:
            return
        
        if key == "ring_palette":
            opts = ["auto", "clean-white", "electric-blue", "neon-cyan", "violet-neon", "magenta"]
            cur = self.settings.get("ring_palette", "auto")
            try: i = opts.index(cur)
            except ValueError: i = 0
            i = (i + delta) % len(opts)
            self.settings["ring_palette"] = opts[i]
            return
        
        # --- per-level edits ---
        if key and key.startswith("level") and ("_hits" in key or "_color" in key):
            try:
                lid = int(key.split("level",1)[1].split("_",1)[0])
                L = LEVELS.get(lid)
                if L:
                    if key.endswith("_hits"):
                        L.hits_required = max(1, min(999, L.hits_required + delta))
                        # jeśli edytujesz aktualny level – zaktualizuj bieżący limit
                        if self.level == lid:
                            self.level_goal = L.hits_required
                return
            except Exception:
                return

        if key == "fullscreen":
            self.settings["fullscreen"] = not self.settings["fullscreen"]
            self._set_display_mode(bool(self.settings["fullscreen"]))
            CFG["display"]["fullscreen"] = bool(self.settings["fullscreen"])
            save_config({"display": {"fullscreen": CFG["display"]["fullscreen"]}})
            return
        
        if key == "glitch_enabled":
            self.settings["glitch_enabled"] = not bool(self.settings.get("glitch_enabled", True))
            self.fx.set_enabled(bool(self.settings["glitch_enabled"]))  # efekt włącza/wyłącza się natychmiast
            return
        
        if key == "highscore_reset":
            self.highscore = 0
            CFG["highscore"] = 0
            save_config({"highscore": 0})
            return
        
        if key == "levels_active":
            new_val = int(max(1, min(LEVELS_MAX, int(self.levels_active) + delta)))
            # dobuduj brakujące LevelCfg przy zwiększaniu
            if new_val > self.levels_active:
                for lid in range(self.levels_active + 1, new_val + 1):
                    _ensure_level_exists(lid)
            self.levels_active = new_val
            # korekta kursora w tabeli, jeśli wypadł poza zakres
            if self.level_table_sel_row > self.levels_active:
                self.level_table_sel_row = self.levels_active
                self.level_table_sel_col = min(self.level_table_sel_col, 4)
            return

        step = {
            "target_time_initial": 0.1,
            "target_time_step": 0.01,
            "target_time_min": 0.05,
            "lives": 1,
            "music_volume": 0.05,
            "sfx_volume": 0.05,
            "timed_rule_bonus": 0.5,
        }.get(key, 0.0)

        if step == 0.0:
            return

        cur = self.settings[key]
        self.settings[key] = (cur + (step * delta)) if isinstance(cur, float) else (cur + delta)
        clamp_settings(self.settings)

        if key == "music_volume" and self.music_ok:
            pygame.mixer.music.set_volume(float(self.settings["music_volume"]))

        elif key == "sfx_volume":
            v = float(self.settings["sfx_volume"])
            for s in getattr(self, "sfx", {}).values():
                s.set_volume(v)
            # opcjonalny odsłuch:
            try:
                if self.sfx.get("point"):
                    self.sfx["point"].play()
            except Exception:
                pass

    def open_settings(self) -> None:
        self.settings = make_runtime_settings(CFG)
        self.settings_idx = 0
        self.settings_move(0)
        self.fx.trigger_glitch(mag=1.0)
        self.scene = Scene.SETTINGS
        self.settings_scroll = 0.0
        self._ensure_selected_visible()

    def settings_save(self) -> None:
        clamp_settings(self.settings)

        for k in ("rule_font_center", "rule_font_pinned"):
            if k in self.settings:
                self.settings.pop(k, None)

        payload = commit_settings(
            self.settings,
            CFG=CFG,
            LEVELS=LEVELS,
            TIMED_DURATION=TIMED_DURATION,
            WINDOWED_DEFAULT_SIZE=WINDOWED_DEFAULT_SIZE,
            RULE_EVERY_HITS=RULE_EVERY_HITS,
        )

        try:
            if "rules" in payload and isinstance(payload["rules"], dict):
                payload["rules"].pop("banner_font_center", None)
                payload["rules"].pop("banner_font_pinned", None)
        except Exception:
            pass

        save_config(payload)

        def _deep_merge(dst, src):
            for k, v in src.items():
                if isinstance(v, dict) and isinstance(dst.get(k), dict):
                    _deep_merge(dst[k], v)
                else:
                    dst[k] = v
        _deep_merge(CFG, payload)

        try:
            if "rules" in CFG and isinstance(CFG["rules"], dict):
                CFG["rules"].pop("banner_font_center", None)
                CFG["rules"].pop("banner_font_pinned", None)
        except Exception:
            pass

        apply_levels_from_cfg(CFG)

        if self.music_ok:
            pygame.mixer.music.set_volume(float(self.settings.get("music_volume", CFG["audio"]["music_volume"])))
        for sfx in getattr(self, "sfx", {}).values():
            sfx.set_volume(float(self.settings.get("sfx_volume", CFG["audio"]["sfx_volume"])))

        self._set_display_mode(bool(self.settings.get("fullscreen", CFG["display"]["fullscreen"])))
        self._rebuild_fonts()
        self.fx.trigger_glitch(mag=1.0)
        self.scene = Scene.MENU

    def settings_cancel(self) -> None:
        self.fx.trigger_glitch(mag=1.0)
        self.scene = Scene.MENU

    def _apply_modifiers_to_fields(self, L: LevelCfg) -> None:
        # wyczyść
        L.rules = []
        L.rotations_per_level = 0
        L.memory_mode = False
        L.control_flip_lr_ud = False
        # zastosuj
        for m in (L.modifiers or []):
            if m == "remap":
                L.rules.append(RuleSpec(RuleType.MAPPING, banner_on_level_start=True, periodic_every_hits=RULE_EVERY_HITS))
            elif m == "spin":
                L.rotations_per_level = max(L.rotations_per_level, 3)
            elif m == "memory":
                L.memory_mode = True
            elif m == "joystick":
                L.control_flip_lr_ud = True

    def _set_level_mod_slot(self, lid: int, slot_idx: int, direction: int) -> None:
        # direction: +1 prawo, -1 lewo
        L = LEVELS.get(lid)
        if not L: return
        mods = (L.modifiers or [])[:]
        while len(mods) < 3: mods.append("—")
        cur = mods[slot_idx]
        opts = MODIFIER_OPTIONS[:]  # ["—","remap","spin","memory","joystick"]
        i = opts.index(cur) if cur in opts else 0

        # pętla po opcjach z omijaniem duplikatów w tym samym levelu
        for _ in range(len(opts)):
            i = (i + direction) % len(opts)
            cand = opts[i]
            # dozwól "—" zawsze; inne – tylko jeśli nie zajęte w INNYM slocie
            if cand == "—" or cand not in [mods[j] for j in range(3) if j != slot_idx]:
                mods[slot_idx] = cand
                break

        L.modifiers = mods[:3]
        self._apply_modifiers_to_fields(L)

# ---- # ---- Okno/tryb wyświetlania & rozmiar ---- ----

    def reset_game_state(self) -> None:
        self.level = 1
        self.hits_in_level = 0
        self.level_goal = LEVELS[1].hits_required
        self.score = 0
        self.streak = 0
        self.best_streak = 0 
        self.final_total = 0
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
        self.level_goal = int(max(1, self.level_cfg.hits_required))

        # wyczyść reguły poprzedniego levelu (instalacja konkretnych nastąpi po INSTRUCTION)
        self.rules.install([])

        # odtwórz pola z listy wybranych modów (z tabeli)
        self._apply_modifiers_to_fields(self.level_cfg)

        # rotacje / memory / instrukcja — jak u Ciebie
        self._plan_rotations_for_level()
        self.memory_show_icons = True
        self.instruction_text = f"LEVEL {lvl}"
        self.instruction_until = float('inf')
        self.scene = Scene.INSTRUCTION
        self.tutorial = build_tutorial_for_level(self)
        self.instruction_intro_t = self.now()
        self.instruction_intro_dur = float(INSTRUCTION_FADE_IN_SEC)

        if self.level_cfg.rotations_per_level > 0:
            self.start_ring_rotation(dur=0.8, spins=2.0, swap_at=0.5)
            self.did_start_rotation = True

        if self.level_cfg.memory_mode:
            self.memory_show_icons = True
            
        self._recompute_keymap()

    def _plan_rotations_for_level(self) -> None:
        self.rotation_breaks = set()
        self.did_start_rotation = False
        N = self.level_cfg.rotations_per_level
        if N > 0:
            seg = max(1, self.level_goal // N)   # np. 15//3 = 5 → progi po 5 i 10 (startowa rotacja robiona osobno)
            for i in range(1, N):                # „w trakcie”
                self.rotation_breaks.add(i * seg)

    def level_up(self) -> None:
        if self.level < self.levels_active:
            self.level += 1
            self.hits_in_level = 0
            self.apply_level(self.level)  # mapping na starcie odpali się po INSTRUCTION

    def new_target(self) -> None:
        prev = self.target
        choices = [s for s in SYMS if s != prev] if prev else SYMS
        self.target = random.choice(choices)
        self.target_deadline = self.now() + self.target_time if self.mode is Mode.SPEEDUP else None
        self.symbol_spawn_time = self.now()
        self.fx.stop_pulse('symbol')
        self.fx.stop_pulse('timer')

    def _start_mapping_banner(self, from_pinned: bool = False) -> None:
        now = self.now()
        self.banner.start(now, from_pinned=from_pinned)
        self.pause_start = now
        self.pause_until = self.banner.active_until
        if self.mode is Mode.TIMED:
            self.time_left += ADDITIONAL_RULE_TIME 
        if self.level_cfg.memory_mode:
            self.memory_preview_armed = True
            self.memory_hide_deadline = 0.0

    def _enter_gameplay_after_instruction(self) -> None:
        self.scene = Scene.GAME
        self.tutorial = None
        if self.mode is Mode.TIMED:
            self._last_tick = self.now()

        if self.level_cfg.memory_mode:
            self.memory_show_icons = True
            self.memory_moves_count = 0
            self.memory_hide_deadline = 0.0   
            self.memory_preview_armed = True

        # 1) Zainstaluj reguły DLA TEGO levelu (czyści poprzednie)
        self.rules.install(self.level_cfg.rules)

        # 2) Jeśli level wymaga banera mappingu na starcie – wylosuj TERAZ (po instrukcji) i uruchom baner
        mapping_spec = next((s for s in (self.level_cfg.rules or [])
                            if s.type is RuleType.MAPPING and s.banner_on_level_start), None)
        if mapping_spec:
            self.rules.roll_mapping(SYMS)
            self._start_mapping_banner(from_pinned=False)
        else:
            if self.level_cfg.memory_mode and self.memory_preview_armed:
                self._memory_start_preview(reset_moves=False, force_unhide=False)

        # 3) Nowy target na start rozgrywki
        self.new_target()

    def _cleanup_exit_slide_if_ready(self) -> None:
        if not self.exit_dir_pos:
            return
        if self.fx.is_exit_active():
            return
        self.fx.clear_exit()
        self.exit_dir_pos = None
        if self.scene is Scene.GAME and not self.banner.is_active(self.now()):
            self.new_target()

# ---- Pętla gry i wejścia (flow rozgrywki) ----

    def _last_editable_settings_idx(self) -> int:
        items = self.settings_items()
        for i in range(len(items) - 1, -1, -1):
            if items[i][2] is not None:
                return i
        return 0

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
                if event.key == pygame.K_RETURN:
                    self.settings_save()
                    return

                # ←/→ – w LIŚCIE: zmiana wartości; w TABELI: edycja aktywnej komórki
                if event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                    delta = -1 if event.key == pygame.K_LEFT else +1
                    if self.settings_focus_table:
                        col = max(1, min(4, self.level_table_sel_col))
                        lid = self.level_table_sel_row
                        if col == 1:
                            L = LEVELS.get(lid)
                            if L:
                                L.hits_required = max(1, min(999, L.hits_required + delta))
                                if self.level == lid:
                                    self.level_goal = L.hits_required
                        else:
                            self._set_level_mod_slot(lid, col - 2, delta)  # slot 0..2
                    else:
                        self.settings_adjust(delta)
                    return

                # ↓ – w LIŚCIE: ruch w dół / wejście do tabeli; w TABELI: następna kolumna, po ostatniej → następny wiersz
                if event.key == pygame.K_DOWN:
                    if self.settings_focus_table:
                        if self.level_table_sel_col < 4:
                            self.level_table_sel_col += 1
                        else:
                            if self.level_table_sel_row < self.levels_active:
                                self.level_table_sel_row += 1
                                self.level_table_sel_col = 1
                        return
                    else:
                        last_idx = self._last_editable_settings_idx()
                        if self.settings_idx == last_idx:
                            self.settings_focus_table = True
                            self.level_table_sel_row = 1
                            self.level_table_sel_col = 1  # Points required
                            self._ensure_selected_visible()
                        else:
                            self.settings_move(+1)
                        return

                # ↑ – w LIŚCIE: ruch w górę; w TABELI: poprzednia kolumna, przed pierwszą → poprzedni wiersz, a z (row1,col1) → powrót do listy
                if event.key == pygame.K_UP:
                    if self.settings_focus_table:
                        if self.level_table_sel_col > 1:
                            self.level_table_sel_col -= 1
                        else:
                            if self.level_table_sel_row > 1:
                                self.level_table_sel_row -= 1
                                self.level_table_sel_col = 4
                            else:
                                # wyjście z tabeli na ostatnią edytowalną pozycję listy
                                self.settings_focus_table = False
                                self.settings_idx = self._last_editable_settings_idx()
                        return
                    else:
                        self.settings_move(-1)
                        return
            
            elif self.scene is Scene.INSTRUCTION:
                # ENTER lub SPACE = skip → natychmiast start gry
                if event.key in (pygame.K_RETURN, pygame.K_SPACE) or event.key in self.key_to_pos:
                    self._enter_gameplay_after_instruction()
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

        # MEMORY ruchy
        if self.level_cfg.memory_mode and self.memory_show_icons:
            self.memory_moves_count += 1
            if self.memory_moves_count >= MEMORY_HIDE_AFTER_MOVES:
                self.memory_show_icons = False

        required = self.rules.apply(self.target)
        if name == required:
            # --- DOBRA ODPOWIEDŹ ---
            self.streak += 1
            if self.streak > self.best_streak:
                self.best_streak = self.streak
            self.score += 1

            # pulse
            self.fx.trigger_pulse('score')
            try:
                hit_pos = next(p for p, s in self.ring_layout.items() if s == required)
                self.fx.trigger_pulse_ring(hit_pos)
            except StopIteration:
                pass

            if self.sfx.get("point"): self.sfx["point"].play()
            if self.streak and self.streak % 10 == 0:
                self.fx.trigger_pulse_streak()
            self.hits_in_level += 1

            if self.mode is Mode.TIMED:
                self.time_left += 1.0
            else:  # SPEEDUP
                step = float(self.settings.get("target_time_step", TARGET_TIME_STEP))
                tmin = float(self.settings.get("target_time_min", TARGET_TIME_MIN))
                self.target_time = max(tmin, self.target_time + step)

            # cykliczny remap (baner)
            if self.rules.on_correct():
                self.rules.roll_mapping(SYMS)
                self._start_mapping_banner(from_pinned=True)

            # rotacje w levelu
            if self.level_cfg.rotations_per_level > 0 and self.hits_in_level in self.rotation_breaks:
                self.start_ring_rotation(dur=0.8, spins=2.0, swap_at=0.5)

            # Level up? Przerywamy flow (instrukcja wystartuje nowy cel później)
            if self.hits_in_level >= self.level_goal:
                self.level_up()
                if self.scene is Scene.INSTRUCTION:
                    self._lock_inputs()
                    return

            # Spróbuj uruchomić exit-slide; jeśli nie — od razu nowy target
            if not self._try_start_exit_slide(required):
                self.new_target()

            self._lock_inputs()
            return

        # --- ZŁA ODPOWIEDŹ ---
        if self.sfx.get("wrong"): self.sfx["wrong"].play()
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
        else:  # SPEEDUP
            if self.lives_enabled():
                self.lives -= 1
                if self.lives <= 0:
                    self.end_game()

    def update(self, iq: InputQueue) -> None:
        now = self.now()
        self.fx.maybe_schedule_text_glitch()

        # --- REMAP banner: detekcja końca animacji (zbocze opadające) ---
        banner_active = self.banner.is_active(now)
        if self._banner_was_active and not banner_active:
            if self.level_cfg.memory_mode and self.memory_preview_armed:
                self._memory_start_preview(reset_moves=False, force_unhide=False)
        self._banner_was_active = banner_active

        # debounce
        if self.lock_until_all_released and not self.keys_down and now >= self.accept_after:
            self.lock_until_all_released = False
        
        # INSTRUKCJA: czekamy do końca timera albo na skip
        if self.scene is Scene.INSTRUCTION:
            _ = iq.pop_all()

            # 1) odpal/aktualizuj tutorial
            if self.tutorial:
                self.tutorial.update()
                # 2) gdy tutorial skończył wszystkie scenki — przejście do gry
                if self.tutorial.is_finished():
                    self._enter_gameplay_after_instruction()
                    return

            # 3) fallback: jeśli kiedyś jednak ustawisz licznik czasu – też zadziała
            if self.instruction_until != float('inf') and self.now() >= self.instruction_until:
                self._enter_gameplay_after_instruction()
            return

        if self.scene is not Scene.GAME:
            _ = iq.pop_all()
            return
        
        if banner_active:
            _ = iq.pop_all()
            # nie licz upływu czasu w TIMED, „zamrażamy” też timeout targetu
            self._last_tick = now
            return

        # po „odkorkowaniu” pauzy:
        if self.pause_until and now >= self.pause_until:
            paused = max(0.0, self.pause_until - (self.pause_start or self.pause_until))
            self.pause_start = 0.0
            self.pause_until = 0.0
            if self.target_deadline is not None:
                self.target_deadline += paused
            self._last_tick = now

            self._cleanup_exit_slide_if_ready()

        # --- PULSE SYMBOLU + TIMERA, gdy minęła połowa czasu na target (SPEEDUP) ---
        if (self.scene is Scene.GAME and self.mode is Mode.SPEEDUP and
            self.target is not None and self.target_deadline is not None and
            self.target_time > 0):

            now = self.now()
            remaining = max(0.0, self.target_deadline - now)
            left_ratio = remaining / max(1e-6, self.target_time)

            if left_ratio <= 0.5:
                # symbol — jednorazowo przy pierwszym wejściu poniżej 50% (opcjonalnie)
                if not self.fx.is_pulse_active('symbol'):
                    # jeśli nie chcesz jednorazowego symbolu, usuń tę linijkę
                    self.fx.trigger_pulse_symbol()

                # timer — ma pulsować CAŁY czas od 50% do końca:
                if not self.fx.is_pulse_active('timer'):
                    self.fx.trigger_pulse('timer')

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
            if self.memory_hide_deadline > 0.0 and now >= self.memory_hide_deadline:
                self.memory_show_icons = False

        self._cleanup_exit_slide_if_ready()

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

    def draw_text(self, text: str, *, pos: Optional[tuple[float,float]] = None,
                font: Optional[pygame.font.Font] = None, size_px: Optional[int] = None,
                color=INK, shadow=True, glitch=True, scale: float = 1.0,
                alpha: Optional[int] = None, shadow_offset=TEXT_SHADOW_OFFSET) -> pygame.Surface:
        if font is None:
            px = self.px(size_px) if size_px else self.font.get_height()
            font = self._font(px)

        render_text = self._glitch_text(text) if (glitch and self.fx.is_text_glitch_active()) else text
        base = font.render(render_text, True, color)

        if scale != 1.0:
            bw, bh = base.get_size()
            base = pygame.transform.smoothscale(base, (max(1, int(bw*scale)), max(1, int(bh*scale))))

        out = base
        if shadow:
            dx, dy = shadow_offset
            sh = self._shadow_text(base)
            surf = pygame.Surface((base.get_width()+max(0,int(dx)), base.get_height()+max(0,int(dy))), pygame.SRCALPHA)
            surf.blit(sh, (int(dx), int(dy))); surf.blit(base, (0, 0))
            out = surf

        if alpha is not None:
            out.set_alpha(alpha)

        if pos is not None:
            x, y = pos
            self.screen.blit(out, (int(x), int(y)))

        return out

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

    def _draw_mod_chip(self, text: str, x: int, y: int, col, *, scale: float = 1.0) -> pygame.Rect:
        pad_x = int(self.px(8) * scale)
        pad_y = int(self.px(4) * scale)
        tw, th = self.font.size(text.upper())
        w, h = int(tw * scale) + pad_x * 2, int(th * scale) + pad_y * 2
        rect = pygame.Rect(x, y, w, h)
        self._draw_round_rect(self.screen, rect, (20,22,30,160),
                            border=(*col, 220), border_w=1, radius=int(self.px(10) * scale))
        self.draw_text(text.upper(), pos=(x + pad_x, y + pad_y),
                    font=self.font, color=col, shadow=True, glitch=False, scale=scale)
        return rect

    def _draw_cell_underline(self, cell: pygame.Rect, *, inset_px: int, thickness: int) -> None:
        r = cell.inflate(-inset_px*2, -inset_px*2)
        y = r.bottom - max(2, thickness)
        x1 = r.left
        x2 = r.right
        pygame.draw.line(self.screen, (120, 200, 255), (x1, y), (x2, y), max(2, thickness))

    def _draw_levels_table(self, top_y: int, max_height: int | None = None, *, scale_override: float | None = None) -> None:
        raw_h = self._levels_table_height()
        scale = float(scale_override) if scale_override is not None else 1.0

        cols = ["LEVEL", "POINTS", "MODIFIER 1", "MODIFIER 2", "MODIFIER 3"]

        def S(v: int) -> int:
            # używamy obliczonego 'scale', nie scale_override bezpośrednio
            return max(1, int(self.px(v) * scale))

        base_col_w = [S(90), S(120), S(170), S(170), S(170)]
        base_table_w = sum(base_col_w)

        side_pad = int(self.w * 0.01)
        avail_w = max(1, self.w - side_pad * 2)

        # W orientacji horyzontalnej ogranicz szerokość tabeli i wyśrodkuj
        if self.w > self.h:
            avail_w = min(avail_w, SETTINGS_TABLE_MAX_W)

        k = avail_w / max(1, base_table_w)
        col_w = [max(1, int(round(w * k))) for w in base_col_w]

        delta = avail_w - sum(col_w)
        col_w[-1] += delta  
        table_w = avail_w
        x0 = (self.w - table_w) // 2 if table_w < (self.w - side_pad * 2) else side_pad

        y = top_y

        # header
        header_h = S(28)
        self._draw_round_rect(self.screen, pygame.Rect(x0, y, table_w, header_h),
                            (22,26,34,180), border=(120,200,255,180), border_w=1, radius=S(8))
        cx = x0
        for i, name in enumerate(cols):
            self.draw_text(name, pos=(cx + S(8), y + S(6)),
                        color=ACCENT, font=self.font, shadow=True, glitch=False, scale=scale)
            cx += col_w[i]
        y += header_h + S(6)

        self._level_table_cells = {}
        row_h = S(32)
        for row in range(1, self.levels_active + 1):
            L = LEVELS.get(row)
            if not L:
                continue
            rr = pygame.Rect(x0, y, table_w, row_h)
            self._draw_round_rect(self.screen, rr, (16,18,24,140), border=(40,60,90,140),
                                border_w=1, radius=S(6))
            cx = x0

            # col 0 (LEVEL) — wycentrowany tekst
            cell = pygame.Rect(cx, y, col_w[0], row_h)
            txt = str(row)
            tw, th = self.font.size(txt)
            self.draw_text(txt,
                        pos=(cell.centerx - int(tw*scale)/2, cell.centery - int(th*scale)/2),
                        color=INK, font=self.font, shadow=True, glitch=False, scale=scale)
            self._level_table_cells[(row, 0)] = cell
            cx += col_w[0]

            # col 1 (POINTS / hits_required) — wycentrowany tekst
            cell = pygame.Rect(cx, y, col_w[1], row_h)
            pts = str(getattr(L, "hits_required", 15))
            tw, th = self.font.size(pts)
            self.draw_text(pts,
                        pos=(cell.centerx - int(tw*scale)/2, cell.centery - int(th*scale)/2),
                        color=INK, font=self.font, shadow=True, glitch=False, scale=scale)
            self._level_table_cells[(row, 1)] = cell
            cx += col_w[1]

            # cols 2..4 (mod chips) — chip wycentrowany w komórce
            mods = (L.modifiers or [])[:]
            while len(mods) < 3: mods.append("—")
            for c in range(3):
                cell = pygame.Rect(cx, y, col_w[2 + c], row_h)
                tag = mods[c]
                if tag == "—":
                    # myślnik wycentrowany
                    m = "—"
                    tw, th = self.font.size(m)
                    self.draw_text(m,
                                pos=(cell.centerx - int(tw*scale)/2, cell.centery - int(th*scale)/2),
                                color=(170,180,190), font=self.font, shadow=True, glitch=False, scale=scale)
                else:
                    # policz rozmiar chipa tak jak _draw_mod_chip, żeby go wycentrować
                    pad_x = int(self.px(8) * scale)
                    pad_y = int(self.px(4) * scale)
                    tw, th = self.font.size(tag.upper())
                    w = int(tw * scale) + pad_x * 2
                    h = int(th * scale) + pad_y * 2
                    chip_x = int(cell.centerx - w/2)
                    chip_y = int(cell.centery - h/2)
                    col = MOD_COLOR.get("memory" if tag == "memory" else ("invert" if tag == "joystick" else tag), INK)
                    self._draw_mod_chip(tag, chip_x, chip_y, col, scale=scale)
                self._level_table_cells[(row, 2 + c)] = cell
                cx += col_w[2 + c]

            if self.settings_focus_table and row == self.level_table_sel_row:
                sel = self._level_table_cells.get((row, self.level_table_sel_col))
                if sel:
                    self._draw_cell_underline(sel, inset_px=S(6), thickness=S(3))

            y += row_h + S(6)

        # legenda — wycentrowana względem tabeli (z paddingiem), nie całego ekranu
        legend = "Legend: remap (magenta) · spin (gold) · memory (red) · inverted joystick (green)"
        lw, _ = self.font.size(legend)
        legend_x = x0 + max(0, (table_w - int(lw * scale)) // 2)
        self.draw_text(legend, pos=(legend_x, y + S(4)),
                    color=(200,210,225), font=self.font, shadow=True, glitch=False, scale=scale)

    def _levels_table_height(self) -> int:
        header_h = self.px(28)
        row_h    = self.px(30)
        gap      = self.px(6)
        legend_h = self.font.get_height() + self.px(4)
        rows_h   = self.levels_active * (row_h + gap)
        return header_h + rows_h + legend_h

    def _soft_glow(self, base: pygame.Surface, color=(120,210,255,60), scale=1.12, passes=2) -> pygame.Surface:
        bw, bh = base.get_size()
        glow_w = int(bw * scale)
        glow_h = int(bh * scale)
        out = pygame.Surface((glow_w, glow_h), pygame.SRCALPHA)
        # skopiuj i powiększ bazę kilka razy z lekkim przesunięciem
        for i in range(passes):
            k = 1.0 + (scale - 1.0) * (i + 1) / passes
            sw = max(1, int(bw * k))
            sh = max(1, int(bh * k))
            s = pygame.transform.smoothscale(base, (sw, sh))
            # zabarw na kolor poświaty
            tint = pygame.Surface((sw, sh), pygame.SRCALPHA)
            tint.fill(color)
            s.blit(tint, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            dx = (glow_w - sw) // 2
            dy = (glow_h - sh) // 2
            out.blit(s, (dx, dy), special_flags=pygame.BLEND_PREMULTIPLIED)
        return out

    def _render_title_remap_minimal(self) -> pygame.Surface:
        # REM + △ + P  (REMAP)
        left_surf  = self.big.render("REM", True, MENU_TITLE_PRIMARY_COLOR)
        right_surf = self.big.render("P",   True, MENU_TITLE_PRIMARY_COLOR)

        H = max(left_surf.get_height(), right_surf.get_height())

        # stały rozmiar trójkąta (ZERO skalowania geometrii)
        tri_h = int(H * MENU_TITLE_TRIANGLE_SCALE)
        tri_w = int(tri_h * 0.9)
        thickness = max(2, int(SYMBOL_DRAW_THICKNESS * (H / self.big.get_height())))

        # stały tracking
        gap = int(self.w * MENU_TITLE_LETTER_SPACING)

        total_w = left_surf.get_width() + gap + tri_w + gap + right_surf.get_width()
        total_h = H
        title = pygame.Surface((total_w, total_h), pygame.SRCALPHA)

        x = 0
        # LEWA część (REM)
        title.blit(self._shadow_text(left_surf), (x + 2, 2))
        title.blit(left_surf, (x, 0))
        x += left_surf.get_width() + gap

        # TRÓJKĄT jako 'A' — osadzony na baseline, bez skalowania
        tri_rect = pygame.Rect(0, 0, tri_w, tri_h)
        tri_rect.midbottom = (x + tri_w // 2, total_h)
        a = (tri_rect.centerx, tri_rect.top)
        b = (tri_rect.left, tri_rect.bottom)
        c = (tri_rect.right, tri_rect.bottom)
        pygame.draw.polygon(title, MENU_TITLE_TRIANGLE_COLOR, [a, b, c], thickness)
        x += tri_w + gap

        # PRAWA część (P)
        title.blit(self._shadow_text(right_surf), (x + 2, 2))
        title.blit(right_surf, (x, 0))

        # „oddech” tylko w poświacie – zmieniamy alfa, nie rozmiar
        t = self.now()
        # 0.5 ↔ 1.0 intensywności
        glow_alpha = int(60 + 40 * (0.5 + 0.5 * math.sin(t * 1.0)))
        glow_color = (MENU_TITLE_GLOW_COLOR[0], MENU_TITLE_GLOW_COLOR[1],
                    MENU_TITLE_GLOW_COLOR[2], glow_alpha)

        glow = self._soft_glow(title, glow_color, MENU_TITLE_GLOW_SCALE, MENU_TITLE_GLOW_PASSES)
        out = pygame.Surface(glow.get_size(), pygame.SRCALPHA)
        ox = (glow.get_width()  - title.get_width())  // 2
        oy = (glow.get_height() - title.get_height()) // 2
        out.blit(glow, (0, 0))
        out.blit(title, (ox, oy))
        return out

    def _draw_neon_pill(self, rect: pygame.Rect, color=(90,200,255,75), layers: int = 4, scale_step: float = 0.08):
        cx, cy = rect.center
        w, h = rect.size
        for i in range(layers, 0, -1):
            k = 1.0 + i * scale_step
            rw = int(w * k)
            rh = int(h * k)
            alpha = max(10, int(color[3] * (i / layers)))
            surf = pygame.Surface((rw, rh), pygame.SRCALPHA)
            pygame.draw.rect(surf, (color[0], color[1], color[2], alpha), surf.get_rect(), border_radius=max(8, int(rh*0.45)))
            self.screen.blit(surf, (cx - rw//2, cy - rh//2), special_flags=pygame.BLEND_PREMULTIPLIED)

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
        sym = SYMBOLS.get(name)
        if not sym:
            # awaryjnie — okrąg w kolorze INK
            pygame.draw.circle(surface, INK, rect.center, int(min(rect.w, rect.h)*0.3), max(1, SYMBOL_DRAW_THICKNESS))
            return
        sym.draw(surface, rect, images=self.images, cfg=self.cfg)

    def _draw_label_value_vstack(self, *, label: str, value: str, left: bool, anchor_rect: pygame.Rect) -> None:
        lab = self.draw_text(label,  color=HUD_LABEL_COLOR, font=self.hud_label_font, shadow=True)
        val = self.draw_text(value,  color=HUD_VALUE_COLOR, font=self.hud_value_font, shadow=True)

        total_h = lab.get_height() + 2 + val.get_height()
        y = anchor_rect.centery - total_h // 2
        if left:
            lx = vx = anchor_rect.left
        else:
            lx = anchor_rect.right - lab.get_width()
            vx = anchor_rect.right - val.get_width()

        self.screen.blit(lab, (lx, y))
        self.screen.blit(val, (vx, y + lab.get_height() + 2))

    def _draw_label_value_vstack_center(
        self, *, label: str, value: str, anchor_rect: pygame.Rect,
        label_color: Tuple[int,int,int] = HUD_LABEL_COLOR,
        value_color: Tuple[int,int,int] = HUD_VALUE_COLOR,
    ) -> None:
        lab = self.draw_text(label, color=label_color, font=self.hud_label_font, shadow=True)
        val = self.draw_text(value, color=value_color, font=self.hud_value_font, shadow=True)

        gap = 2
        total_h = lab.get_height() + gap + val.get_height()
        y  = anchor_rect.centery - total_h // 2
        lx = anchor_rect.centerx - lab.get_width() // 2
        vx = anchor_rect.centerx - val.get_width() // 2

        self.screen.blit(lab, (lx, y))
        self.screen.blit(val, (vx, y + lab.get_height() + gap))

    def _draw_settings_row(self, *, label: str, value: str, y: float, selected: bool) -> float:
        font = self.settings_font
        axis_x = self.w // 2
        gap = self.px(SETTINGS_CENTER_GAP)

        col = ACCENT if selected else INK
        lab = self.draw_text(label, color=col, font=font, shadow=True, glitch=False)
        val = self.draw_text(value, color=col, font=font, shadow=True, glitch=False)

        row_h = max(lab.get_height(), val.get_height())
        label_x = axis_x - gap - lab.get_width()
        label_y = y + (row_h - lab.get_height()) / 2
        value_x = axis_x + gap
        value_y = y + (row_h - val.get_height()) / 2

        self.screen.blit(lab, (label_x, label_y))
        self.screen.blit(val, (value_x, value_y))
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

    def _draw_underline_segment_with_shadow(self, x1: int, x2: int, y: int, th: int, col) -> None:
        if x2 < x1:
            x1, x2 = x2, x1
        # cień – prostokąt z alhą, delikatnie grubszy i przesunięty w dół
        sx, sy = TOPBAR_UNDERLINE_SHADOW_OFFSET
        shadow_h = th + TOPBAR_UNDERLINE_SHADOW_EXTRA_THICK
        shadow_rect = pygame.Rect(x1 + sx, y - shadow_h // 2 + sy, x2 - x1, shadow_h)
        pygame.draw.rect(self.screen, TOPBAR_UNDERLINE_SHADOW_COLOR, shadow_rect,
                        border_radius=TOPBAR_UNDERLINE_SHADOW_RADIUS)
        # właściwa linia
        pygame.draw.line(self.screen, col, (x1, y), (x2, y), th)

    def _draw_hud(self) -> None:
        # --- pełne tło topbara: od lewej do prawej krawędzi ---
        top_bg = pygame.Surface((self.topbar_rect.width, self.topbar_rect.height), pygame.SRCALPHA)
        top_bg.fill(SCORE_CAPSULE_BG)  # (22, 26, 34, 170) — jak kapsuła SCORE
        self.screen.blit(top_bg, self.topbar_rect.topleft)

        # --- underline --- #
        cap = self.score_capsule_rect
        y   = self.topbar_rect.bottom - TOPBAR_UNDERLINE_THICKNESS // 2
        th  = TOPBAR_UNDERLINE_THICKNESS
        col = TOPBAR_UNDERLINE_COLOR

        left_end    = max(self.topbar_rect.left, cap.left - 1)
        right_start = min(self.topbar_rect.right, cap.right + 1)

        if left_end > self.topbar_rect.left:
            self._draw_underline_segment_with_shadow(self.topbar_rect.left, left_end, y, th, col)

        if right_start < self.topbar_rect.right:
            self._draw_underline_segment_with_shadow(right_start, self.topbar_rect.right, y, th, col)

        # --- STREAK / HIGHSCORE
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
        lab = self.draw_text("STREAK", color=HUD_LABEL_COLOR, font=self.hud_label_font, shadow=True)
        label_x = left_block.centerx - lab.get_width() // 2
        label_y = left_block.centery - lab.get_height() - 2
        self.screen.blit(lab, (label_x, label_y))

        scale = self.fx.pulse_scale('streak')
        val = self.draw_text(str(self.streak), color=HUD_VALUE_COLOR, font=self.hud_value_font, shadow=True, scale=scale)
        vx = left_block.centerx - val.get_width() // 2
        vy = label_y + lab.get_height() + 2
        self.screen.blit(val, (vx, vy))

        # HIGHSCORE po prawej (bez zmian)
        hs_label_color = (255, 230, 140) if self.score > self.highscore else HUD_LABEL_COLOR
        self._draw_label_value_vstack_center(
            label="HIGHSCORE",
            value=str(self.highscore),
            anchor_rect=right_block,
            label_color=hs_label_color,          
            value_color=HUD_VALUE_COLOR,         
        )

        # --- kapsuła SCORE ---
        sx, sy = SCORE_CAPSULE_SHADOW_OFFSET
        shadow_rect = cap.move(sx, sy)
        self._draw_round_rect(self.screen, shadow_rect, SCORE_CAPSULE_SHADOW, radius=SCORE_CAPSULE_RADIUS + 2)
        self._draw_round_rect(
            self.screen, cap, SCORE_CAPSULE_BG,
            border=SCORE_CAPSULE_BORDER_COLOR, border_w=2, radius=SCORE_CAPSULE_RADIUS
        )
        label_surf = self.draw_text("SCORE", color=SCORE_LABEL_COLOR, font=self.score_label_font, shadow=True)
        raw_val = self.draw_text(
            str(self.score),
            color=SCORE_VALUE_COLOR,
            font=self.score_value_font,
            shadow=True,
            scale=self.fx.pulse_scale('score'),
        )

        gap = 2
        total_h = label_surf.get_height() + gap + raw_val.get_height()

        lx = cap.centerx - label_surf.get_width() // 2
        ly = cap.centery - total_h // 2

        vx = cap.centerx - raw_val.get_width() // 2
        vy = ly + label_surf.get_height() + gap

        self.screen.blit(label_surf, (lx, ly))
        self.screen.blit(raw_val, (vx, vy))

        # docelowe Y dla dockowania bannera: poniżej kapsuły SCORE
        margin = self.px(RULE_BANNER_PINNED_MARGIN)
        self._rule_pinned_y = max(self.topbar_rect.bottom + self.px(8), self.score_capsule_rect.bottom + margin)

        # Bottom timer (only in-game)
        if self.scene is Scene.GAME:
            if self.mode is Mode.TIMED:
                self.timebar.draw(self.time_left / TIMED_DURATION, f"{self.time_left:.1f}s")
            elif self.mode is Mode.SPEEDUP and self.target_deadline is not None and self.target_time > 0:
                remaining = max(0.0, self.target_deadline - self.now())
                ratio = remaining / max(0.001, self.target_time)
                self.timebar.draw(ratio, f"{remaining:.1f}s")

    def _blit_bg(self):
        if self.bg_img:
            self.screen.blit(self.bg_img, (0, 0))
        else:
            self.screen.fill(BG)

    def ring_colors(self) -> tuple[tuple[int,int,int], tuple[int,int,int], tuple[int,int,int]]:
        def _lerp(a,b,t):
            t = max(0.0, min(1.0, float(t)))
            return (int(a[0] + (b[0]-a[0])*t),
                    int(a[1] + (b[1]-a[1])*t),
                    int(a[2] + (b[2]-a[2])*t))
        def _pal(name): return RING_PALETTES[name]
        def _lerp_pal(p1, p2, t):
            return (_lerp(p1["base"], p2["base"], t),
                    _lerp(p1["hi"],   p2["hi"],   t),
                    _lerp(p1["soft"], p2["soft"], t))

        sel = str(self.settings.get("ring_palette", "auto"))

        # po pobiciu rekordu — złoto niezależnie od wyboru (feedback)
        if self.score > max(0, self.highscore):
            g = _pal("gold")
            return g["base"], g["hi"], g["soft"]

        if sel != "auto":
            p = _pal(sel)
            return p["base"], p["hi"], p["soft"]

        # AUTO: progres od 0..highscore
        hs = max(1, int(self.highscore))      # unikamy dzielenia przez zero
        prog = max(0.0, min(1.0, self.score / hs))

        names = RING_GRADIENT_ORDER
        if len(names) == 1:
            p = _pal(names[0]); return p["base"], p["hi"], p["soft"]

        segs = len(names) - 1
        x = prog * segs
        i = min(segs - 1, int(x))
        t = x - i
        p1 = _pal(names[i]); p2 = _pal(names[i+1])
        return _lerp_pal(p1, p2, t)

    def _pick_new_ring_layout(self) -> dict[str,str]:
        current = [self.ring_layout[p] for p in RING_POSITIONS]
        symbols = list(SYMS)
        while True:
            random.shuffle(symbols)
            if symbols != current:
                break
        return {pos: sym for pos, sym in zip(RING_POSITIONS, symbols)}

    def start_ring_rotation(self, *, dur: float = 0.8, spins: float = 2.0, swap_at: float = 0.5) -> None:
        now = self.now()
        self.rot_anim.update({
            "active": True,
            "t0": now,
            "dur": float(max(0.15, dur)),
            "spins": float(spins),
            "swap_at": float(max(0.05, min(0.95, swap_at))),
            "swapped": False,
            "from_layout": dict(self.ring_layout),
            "to_layout": self._pick_new_ring_layout(),
        })
        # pauza rozgrywki na czas animacji (bez glitcha)
        self.pause_start = now
        self.pause_until = now + self.rot_anim["dur"]
        # ważne: NIE wywołujemy self.fx.trigger_glitch()

    def _update_ring_rotation_anim(self) -> float:
        if not self.rot_anim["active"]:
            return 0.0
        now = self.now()
        t = (now - self.rot_anim["t0"]) / self.rot_anim["dur"]
        if t >= 1.0:
            # finisz: zatwierdź docelowy layout i wyłącz animację
            self.ring_layout = dict(self.rot_anim["to_layout"])
            self._recompute_keymap()
            self.rot_anim["active"] = False
            self.rot_anim["swapped"] = True
            # MEMORY + SPIN: po faktycznej zmianie układu pokaż go graczowi od nowa
            if self.level_cfg.memory_mode:
                self._memory_start_preview(reset_moves=True, force_unhide=True)
            return 0.0
        # ease-out dla przyjemnego hamowania
        p = self._ease_out_cubic(max(0.0, min(1.0, t)))
        # w połowie obrotu podmień layout (żeby „wymieszać” w locie)
        if (not self.rot_anim["swapped"]) and t >= self.rot_anim["swap_at"]:
            self.ring_layout = dict(self.rot_anim["to_layout"])
            self._recompute_keymap()
            self.rot_anim["swapped"] = True
        # kąt całkowity
        deg = 360.0 * self.rot_anim["spins"] * p
        return deg

    def _draw_spawn_animation(self, surface: pygame.Surface, name: str, rect: pygame.Rect) -> None:
        age = self.now() - self.symbol_spawn_time
        t = 0.0 if SYMBOL_ANIM_TIME <= 0 else min(1.0, max(0.0, age / SYMBOL_ANIM_TIME))
        eased = 1.0 - (1.0 - t) ** 3

        base_size = self.w * SYMBOL_BASE_SIZE_FACTOR
        scale = SYMBOL_ANIM_START_SCALE + (1.0 - SYMBOL_ANIM_START_SCALE) * eased
        scale *= self.fx.pulse_scale('symbol')             # << pulsing z FX
        size = int(base_size * scale)

        end_y = self.h * CENTER_Y_FACTOR
        start_y = end_y + self.h * SYMBOL_ANIM_OFFSET_Y
        cy = start_y + (end_y - start_y) * eased

        dx, dy = self.fx.shake_offset(self.w)              # << shake z FX

        draw_rect = pygame.Rect(0, 0, size, size)
        draw_rect.center = (int(self.w * 0.5 + dx), int(cy + dy))
        self.draw_symbol(surface, name, draw_rect)

        if hasattr(self.fx, "is_exit_active") and self.fx.is_exit_active() and self.exit_dir_pos:
            t = self.fx.exit_progress()
            eased2 = self._ease_out_cubic(t)

            # wektor kierunku zjazdu (od środka ku pozycji na ringu)
            dir_vec = {
                "RIGHT": (1, 0), "LEFT": (-1, 0), "TOP": (0, -1), "BOTTOM": (0, 1)
            }.get(self.exit_dir_pos, (0, 0))

            slide_dist = int(self.w * 0.35)  # jak daleko wypadamy poza ekran
            offx = int(dir_vec[0] * slide_dist * eased2)
            offy = int(dir_vec[1] * slide_dist * eased2)

            # fade out wraz z ruchem
            alpha = int(255 * (1.0 - eased2))

            symbol_layer = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            self.draw_symbol(symbol_layer, name, draw_rect.move(offx, offy))
            # nałóż alpha
            alpha_tint = pygame.Surface(symbol_layer.get_size(), pygame.SRCALPHA)
            alpha_tint.fill((255, 255, 255, alpha))
            symbol_layer.blit(alpha_tint, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            surface.blit(symbol_layer, (0, 0))
            return  # nie rysuj wersji „spawn” drugi raz

    def _draw_gameplay(self):
        self._blit_bg()
        self._draw_hud()

        # bazowy prostokąt pod symbol w centrum (zawsze liczony)
        base_size = int(self.w * SYMBOL_BASE_SIZE_FACTOR)
        base_rect = pygame.Rect(0, 0, base_size, base_size)
        base_rect.center = (int(self.w * 0.5), int(self.h * CENTER_Y_FACTOR))

        # ring
        spin_deg = self._update_ring_rotation_anim()
        self.ring.draw(base_rect.center, base_size, layout=self.ring_layout, spin_deg=spin_deg)

        # jeśli trwa/just-ended exit-slide, NIE rysujemy centralnego symbolu
        if self.exit_dir_pos:
            if self.fx.is_exit_active() and self.fx.exit_symbol:
                # progres + easing
                t = self.fx.exit_progress()
                eased = t * t  # lekki ease-in

                # wektor docelowy (pozycja symbolu na ringu)
                cx, cy = base_rect.center
                r = int(base_rect.width * RING_RADIUS_FACTOR)
                target_xy = {
                    "TOP":    (cx, cy - r),
                    "RIGHT":  (cx + r, cy),
                    "LEFT":   (cx - r, cy),
                    "BOTTOM": (cx, cy + r),
                }[self.exit_dir_pos]

                # idź trochę ZA ikonę na ringu, żeby ładnie „zniknął”
                tx = int(cx + (target_xy[0] - cx) * 1.2 * eased)
                ty = int(cy + (target_xy[1] - cy) * 1.2 * eased)

                # shrink + fade
                scale = (1.0 - 0.25 * eased) * self.fx.pulse_scale('symbol')
                size = max(1, int(self.w * SYMBOL_BASE_SIZE_FACTOR * scale))
                rect = pygame.Rect(0, 0, size, size)
                rect.center = (tx, ty)

                tmp = pygame.Surface((size, size), pygame.SRCALPHA)
                self.draw_symbol(tmp, self.fx.exit_symbol, tmp.get_rect())
                tmp.set_alpha(int(255 * (1.0 - t)))
                self.screen.blit(tmp, rect.topleft)
            else:
                # exit już się skończył, ale nowy target jeszcze nie powstał → nie rysuj nic w centrum
                pass
        else:
            # zwykła animacja pojawienia (tylko jeśli jest target)
            if self.target:
                self._draw_spawn_animation(self.screen, self.target, base_rect)

        # przypięty baner reguły, jeśli aktywny mapping i nie trwa animacja banera
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
                # tło
                self._blit_bg()

                # Tytuł
                title_surf = self._render_title_remap_minimal()
                tw, th = title_surf.get_size()
                sw = max(1, int(tw * MENU_TITLE_GLOBAL_SCALE))
                sh = max(1, int(th * MENU_TITLE_GLOBAL_SCALE))
                title_surf = pygame.transform.smoothscale(title_surf, (sw, sh))
                tw, th = title_surf.get_size()

                ty = int(self.h * MENU_TITLE_Y_FACTOR)      # bez boba
                tx = (self.w - tw) // 2
                self.screen.blit(title_surf, (tx, ty))

                # cienka neonowa belka pod tytułem (stała szerokość; chcemy stabilność)
                bar_margin = self.px(10)
                bar_h = self.px(6)
                bar_w = int(tw * 0.82)
                bx = (self.w - bar_w) // 2
                by = ty + th + bar_margin

                bar = pygame.Surface((bar_w, bar_h), pygame.SRCALPHA)
                bar.fill((120, 210, 255, 90))
                glow = pygame.transform.smoothscale(bar, (int(bar_w * 1.2), int(bar_h * 2.4)))
                grect = glow.get_rect(center=(bx + bar_w // 2, by + bar_h // 2))
                self.screen.blit(glow, grect.topleft)
                self.screen.blit(bar, (bx, by))

                # Badge trybu
                mode_label = "SPEED-UP" if self.mode is Mode.SPEEDUP else "TIMED"
                mode_text = f"Mode: {mode_label}   (M to change)"
                t_surf = self.mid.render(mode_text, True, MENU_MODE_TEXT_COLOR)
                pad_x = self.px(12); pad_y = self.px(8)
                bw = t_surf.get_width() + pad_x * 2
                bh = t_surf.get_height() + pad_y * 2
                bx = (self.w - bw) // 2
                by = by + bar_h + self.px(14)

                badge_rect = pygame.Rect(bx, by, bw, bh)
                pygame.draw.rect(self.screen, MENU_MODE_BADGE_BG, badge_rect, border_radius=MENU_MODE_BADGE_RADIUS)
                pygame.draw.rect(self.screen, MENU_MODE_BADGE_BORDER, badge_rect, width=1, border_radius=MENU_MODE_BADGE_RADIUS)
                self.screen.blit(t_surf, (bx + pad_x, by + pad_y))

                # Hint na dole
                hint = "ENTER = start    ·    O = settings    ·    ESC = quit"
                hf = self.font
                hw, hh = hf.size(hint)
                bottom_gap = self.px(24)
                self.draw_text(hint, pos=(self.w/2 - hw/2, self.h - bottom_gap - hh//4), font=hf, color=(210, 220, 235))

            elif self.scene is Scene.OVER:
                # Minimalny ekran końcowy: TOTAL + formuła + opcjonalny badge
                self._blit_bg()
                cx, cy = self.w // 2, self.h // 2

                # 1) TOTAL (duży)
                total_val = max(0, int(self.final_total or (self.score + self.streak)))
                total_surf = self.draw_text(
                    str(total_val),
                    color=SCORE_VALUE_COLOR,
                    font=self.score_value_font,
                    shadow=True,
                    glitch=False,
                    scale=1.15
                )
                self.screen.blit(
                    total_surf,
                    (cx - total_surf.get_width() // 2, cy - total_surf.get_height() // 2)
                )

                # 2) Formuła pod spodem (czytelna, ale mniejsza)
                formula = f"{self.score} + {self.best_streak} streak"
                fw, fh = self.mid.size(formula)
                self.draw_text(
                    formula,
                    pos=(cx - fw // 2, cy + total_surf.get_height() // 2 + self.px(8)),
                    font=self.mid, color=ACCENT, shadow=True, glitch=False
                )

                # 3) Badge NEW BEST! jeśli pobity rekord
                if total_val >= self.highscore:
                    badge = "NEW BEST!"
                    bx = cx - self.font.size(badge)[0] // 2
                    by = cy - total_surf.get_height() // 2 - self.px(18)
                    self.draw_chip(
                        badge, bx - self.px(12), by - self.px(6),
                        pad=self.px(8), radius=self.px(10),
                        bg=(22, 26, 34, 160), border=(120, 200, 255, 200),
                        text_color=INK, font=self.font
                    )

                # 4) Delikatna podpowiedź na dole
                info_text = "SPACE = play again   ·   ESC = quit"
                iw, ih = self.font.size(info_text)
                self.draw_text(
                    info_text,
                    pos=(cx - iw // 2, self.h - ih - self.px(24)),
                    font=self.font, color=(210, 220, 235), shadow=True, glitch=False
                )

            elif self.scene is Scene.SETTINGS:
                self._blit_bg()
                title_text = "Settings"
                tw, th = self.big.size(title_text)
                self.draw_text(title_text, pos=(self.w / 2 - tw / 2, self.h * SETTINGS_TITLE_Y_FACTOR), font=self.big)

                top_y = int(self.h * SETTINGS_LIST_Y_START_FACTOR)

                help1 = "↑/↓ select · ←/→ adjust"
                help2 = "ENTER save · ESC back"
                help_margin = self.px(SETTINGS_HELP_MARGIN_TOP)
                help_gap    = self.px(SETTINGS_HELP_GAP)
                w1, h1 = self.font.size(help1)
                w2, h2 = self.font.size(help2)
                help_block_h = help_margin + h1 + help_gap + h2 + self.px(12)

                viewport = pygame.Rect(0, top_y, self.w, max(50, self.h - top_y - help_block_h))
                prev_clip = self.screen.get_clip()
                self.screen.set_clip(viewport)

                items = self.settings_items()
                self._settings_row_tops = []
                item_spacing = self.px(SETTINGS_ITEM_SPACING)
                y_probe = top_y
                for i, (label, value, key) in enumerate(items):
                    label_surf = self.settings_font.render(label, True, INK if key is not None else ACCENT)
                    value_surf = self.settings_font.render(value, True, INK if key is not None else ACCENT)
                    row_h = max(label_surf.get_height(), value_surf.get_height())
                    self._settings_row_tops.append((y_probe, row_h))
                    y_probe += row_h + item_spacing
                list_end_y = y_probe  

                raw_table_h = self._levels_table_height()

                available_h = viewport.height

                scale_for_table = 1.0
                if raw_table_h > available_h:
                    scale_for_table = max(0.55, available_h / raw_table_h)

                table_h = int(raw_table_h * scale_for_table)
                gap_list_table = self.px(8)

                content_h = (list_end_y - top_y) + gap_list_table + table_h

                max_scroll = max(0, content_h - viewport.height)
                self.settings_scroll = max(0.0, min(float(max_scroll), float(self.settings_scroll)))

                y = top_y - int(self.settings_scroll)

                for i, (label, value, key) in enumerate(items):
                    selected = (i == self.settings_idx and key is not None and not self.settings_focus_table)
                    row_h = self._draw_settings_row(label=label, value=value, y=y, selected=selected)
                    y += row_h + item_spacing

                table_top = y + gap_list_table
                self._draw_levels_table(table_top, max_height=available_h, scale_override=scale_for_table)

                self.screen.set_clip(prev_clip)

                base_y = self.h - (h1 + help_gap + h2) - self.px(14)
                self.draw_text(help1, pos=(self.w/2 - w1/2, base_y), font=self.font)
                self.draw_text(help2, pos=(self.w/2 - w2/2, base_y + h1 + help_gap), font=self.font)

            elif self.scene is Scene.INSTRUCTION:
                # najpierw tutorial (ring + animacje)
                if self.tutorial:
                    self.tutorial.draw()

                # --- TYTUŁ ---
                title = self.instruction_text or f"LEVEL {self.level}"
                tw, th = self.big.size(title)
                title_y = int(self.h * 0.14)
                self.draw_text(title, pos=(self.w/2 - tw/2, title_y), font=self.big)

                # --- CAPTION POD TYTUŁEM (np. "Follow remap") ---
                if self.tutorial and getattr(self.tutorial, "caption", ""):
                    cap = self.tutorial.caption
                    cw, ch = self.mid.size(cap)
                    cap_margin = self.px(8)
                    self.draw_text(cap, pos=(self.w/2 - cw/2, title_y + th + cap_margin), font=self.mid, color=ACCENT)
                    self.tutorial.show_caption = False

                # --- HINT w prawym dolnym rogu ---
                hint = "ENTER/SPACE = start"
                fnt  = getattr(self, "hint_font", self.font)
                hw, hh = fnt.size(hint)
                pad = self.px(14)
                x = self.w - hw - pad
                y = self.h - hh - pad
                self.screen.blit(fnt.render(hint, True, (0, 0, 0)), (x + 2, y + 2))
                self.screen.blit(fnt.render(hint, True, (220, 200, 120)), (x, y))

                # --- FADE-IN na starcie instrukcji ---
                t = (self.now() - getattr(self, "instruction_intro_t", 0.0)) / max(1e-6, getattr(self, "instruction_intro_dur", 0.0))
                t = max(0.0, min(1.0, t))
                alpha = int(255 * (1.0 - self._ease_out_cubic(t)))  # szybki start, miękkie zejście
                if alpha > 0:
                    overlay = pygame.Surface((self.w, self.h))
                    overlay.set_alpha(alpha)
                    overlay.fill((0, 0, 0))
                    self.screen.blit(overlay, (0, 0))

        finally:
            self.screen = old_screen

        # post FX + present
        final_surface = self.fx.apply_postprocess(self.fb, self.w, self.h)
        self.screen.blit(final_surface, (0, 0))
        pygame.display.flip()

# ============================== MAIN LOOP ============================== #

def main():
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