from __future__ import annotations

from pathlib import Path

import pygame

from .config import CFG

PKG_DIR = Path(__file__).resolve().parent


# --- Palette ----------------------------------------------------------------
BG = (8, 10, 12)                 # default background when no backdrop is loaded
INK = (235, 235, 235)            # primary text colour
ACCENT = (255, 210, 90)          # accent colour for highlights

# Vector symbol palette used when textures are unavailable
SYMBOL_COLORS = {
    "TRIANGLE": (0, 0, 255),   
    "CIRCLE":   (255, 0, 0),
    "CROSS":    (0, 255, 0),   
    "SQUARE":   (255, 215, 0),
}

# --- Layout ----------------------------------------------------------------
PADDING = 0.06                   
GAP = 0.04                       
FPS = int(CFG.get("display", {}).get("fps", 60))    
INPUT_ACCEPT_DELAY = 0.03
TEXT_SHADOW_OFFSET = (2, 2)
UI_RADIUS = 8

# --- Level progression ------------------------------------------------------
LEVEL_GOAL_PER_LEVEL = 15        
LEVELS_ACTIVE_FOR_NOW = 7        
LEVELS_MAX = 10

# --- Game tempo -------------------------------------------------------------
TARGET_TIME_INITIAL = CFG["speedup"]["target_time_initial"]                      
TARGET_TIME_MIN = CFG["speedup"]["target_time_min"]                              
TARGET_TIME_STEP = CFG["speedup"]["target_time_step"]                            
TIMED_DURATION = float(CFG.get("timed", {}).get("duration", 60.0))               
RULE_EVERY_HITS = int(CFG.get("rules", {}).get("every_hits", 3))                 
MAX_LIVES = int(CFG.get("lives", 0))                                             
ADDITIONAL_RULE_TIME = float(CFG["timed"].get("rule_bonus", 5.0))                
MEMORY_HIDE_AFTER_SEC = float(CFG.get("memory_hide_sec", 1.0))

# --- Target symbol animation -----------------------------------------------
CENTER_Y_FACTOR = 0.58            
SYMBOL_BASE_SIZE_FACTOR = 0.28    
SYMBOL_ANIM_TIME = 0.30           
SYMBOL_ANIM_START_SCALE = 0.20    
SYMBOL_ANIM_OFFSET_Y = 0.08       

# Camera shake feedback
SHAKE_effect duration
SHAKE_AMPLITUDE_FACT = 0.012      
SHAKE_FREQ_HZ = 18.0              

# Vector rendering fallbacks for symbols
SYMBOL_DRAW_THICKNESS = 20        
SYMBOL_SQUARE_RADIUS = UI_RADIUS  
SYMBOL_CIRCLE_RADIUS_FACTOR = 0.32        
SYMBOL_TRIANGLE_POINT_FACTOR = 0.9        
SYMBOL_CROSS_K_FACTOR = 1.0               

# --- Post-process glitch ----------------------------------------------------
GLITCH_DURATION = 0.20            
GLITCH_PIXEL_FACTOR_MAX = 0.10    

# --- Text glitch animation --------------------------------------------------
TEXT_GLITCH_DURATION = 0.5        
TEXT_GLITCH_MIN_GAP = 1           
TEXT_GLITCH_MAX_GAP = 5.0         
TEXT_GLITCH_CHAR_PROB = 0.01      
TEXT_GLITCH_CHARSET = "01+-_

EXIT_SLIDE_SEC = 0.12             
INSTRUCTION_FADE_IN_SEC = 1    

# --- Pulse effect -----------------------------------------------------------
# Base timing with per-element multipliers for easy tuning.
PULSE_BASE_DURATION = 0.30        
PULSE_BASE_MAX_SCALE = 1.18       

# Multipliers relative to the base (1.0 keeps the base intensity)
PULSE_KIND_SCALE = {
    "symbol": 1.00,    # pulse applied to the central symbol when the timer reaches half way
    "streak": 1.06,    # pulse for the streak counter
    "banner": 1.04,    # subtle pulse on the rule banner
    "score":  1.10,    # pulse applied to the score readout
    "timer":  1.10,    # pulse applied to the timer bar
}

# Duration overrides per element (defaults to the base when missing)
PULSE_KIND_DURATION = {
    "symbol": 0.30,
    "streak": 0.30,
    "banner": 0.30,
    "score":  0.26,
    "timer":  0.40
}

# --- Timer bar --------------------------------------------------------------
TIMER_BAR_WIDTH_FACTOR = 0.66     
TIMER_BAR_HEIGHT = 18             
TIMER_BAR_BG = (40, 40, 50)       
TIMER_BAR_FILL = (90, 200, 255)   
TIMER_BAR_BORDER = (160, 180, 200)
TIMER_BAR_BORDER_W = 2            
TIMER_BAR_WARN_COLOR = (255, 170, 80)  
TIMER_BAR_CRIT_COLOR = (220, 80, 80)   
TIMER_BAR_WARN_TIME = 0.50        
TIMER_BAR_CRIT_TIME = 0.25        
TIMER_BAR_BORDER_RADIUS = UI_RADIUS     
TIMER_BOTTOM_MARGIN_FACTOR = 0.02 
TIMER_BAR_TEXT_COLOR = INK        
TIMER_FONT_SIZE = 48              
TIMER_POSITION_INDICATOR_W = 4    
TIMER_POSITION_INDICATOR_PAD = 3  
TIMER_LABEL_GAP = 8               

# --- Rule banner -------------------------------------------------------------
RULE_BANNER_PINNED_MARGIN = 25    
RULE_BANNER_IN_SEC = 0.35         
RULE_BANNER_HOLD_SEC = 2.0        
RULE_BANNER_TO_TOP_SEC = 0.35     
RULE_PANEL_BG = (22, 26, 34, 110) 
RULE_PANEL_BORDER = (120, 200, 255)     
RULE_PANEL_BORDER_W = 3           
RULE_PANEL_RADIUS = 30            
RULE_ICON_SIZE_FACTOR = 0.1       
RULE_ICON_GAP_FACTOR = 0.04       
RULE_ARROW_W = 6                  
RULE_ARROW_COLOR = (200, 220, 255)
RULE_PANEL_PAD = 16               
RULE_BANNER_VGAP = 8              
RULE_BANNER_TITLE = "REMAPPING:"   
RULE_BANNER_PIN_SCALE = 0.65      
RULE_SYMBOL_SCALE_CENTER = 1.00   
RULE_SYMBOL_SCALE_PINNED = 0.70   
RULE_BANNER_MIN_W_FACTOR = 0.90   
RULE_BANNER_FONT_CENTER_PX = 64
RULE_BANNER_FONT_PINNED_PX = 40

# --- Mods banner -------------------------------------------------------------
MODS_BANNER_IN_SEC   = 0.40
MODS_BANNER_HOLD_SEC = 1.60
MODS_BANNER_OUT_SEC  = 0.35
MODS_BANNER_TITLE    = "NEW MODS:"

# --- Input ring --------------------------------------------------------------
RING_RADIUS_FACTOR = 1           
RING_THICKNESS = 6               
RING_ICON_SIZE_FACTOR = 0.46     
RING_ALPHA_MAIN  = 245           
RING_ALPHA_SOFT  = 220           
RING_ALPHA_TICKS = 200           
RING_ALPHA_HI    = 255           

# --- Ring layout --------------------------------------------------------------
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
    "random":  (90, 220, 255),   # cyan
}

RING_POSITIONS = ["TOP", "RIGHT", "LEFT", "BOTTOM"]

RING_PALETTES = {
    "clean-white":   {"base": (243,244,246), "hi": (255,255,255), "soft": (209,213,219)},
    "electric-blue": {"base": (96,165,250),  "hi": (37,99,235),   "soft": (147,197,253)},
    "neon-cyan":     {"base": (103,232,249), "hi": (34,211,238),  "soft": (165,243,252)},
    "violet-neon":   {"base": (167,139,250), "hi": (139,92,246),  "soft": (196,181,253)},
    "magenta":       {"base": (236,72,153),  "hi": (219,39,119),  "soft": (249,168,212)},
    "gold":          {"base": (255,210,90),  "hi": (255,230,140), "soft": (245,195,70)},  # used only after beating the high score
}

# Gradient order used when cycling palettes automatically
RING_GRADIENT_ORDER = ["clean-white", "electric-blue", "neon-cyan", "violet-neon", "magenta"]

# --- Aspect ratio ------------------------------------------------------------
ASPECT_RATIO = (9, 16)             
ASPECT_SNAP_MIN_SIZE = (360, 640)  
ASPECT_SNAP_TOLERANCE = 0.0        

# --- Audio ---
MUSIC_FADEOUT_MS = 800             

# --- Window configuration ----------------------------------------------------
WINDOWED_DEFAULT_SIZE = tuple(CFG.get("display", {}).get("windowed_size", (720, 1280)))  
WINDOWED_FLAGS = pygame.RESIZABLE  


# --- Screen layout metrics ----------------------------------------------------
MENU_TITLE_Y_FACTOR = 0.28           
MENU_MODE_GAP = 20                   
MENU_HINT_GAP = 48                   
MENU_HINT2_EXTRA_GAP = 12            
SETTINGS_TABLE_MAX_W = 1100          

# --- Menu title styling -------------------------------------------------------
MENU_TITLE_GLOBAL_SCALE = 1.18
MENU_TITLE_PRIMARY_COLOR = INK                 
MENU_TITLE_NEON_COLOR = (90, 200, 255, 75)     
MENU_TITLE_NEON_LAYERS = 4                     
MENU_TITLE_NEON_SCALE_STEP = 0.08              
MENU_SUBTLE_TEXT_COLOR = (210, 210, 220)       
MENU_CHIP_BG = (20, 22, 30, 160)               
MENU_CHIP_BORDER = (120, 200, 255, 200)
MENU_CHIP_RADIUS = 14
MENU_TITLE_TRIANGLE_COLOR = (120, 210, 255)      
MENU_TITLE_GLOW_COLOR = (120, 210, 255, 60)      
MENU_TITLE_GLOW_PASSES = 2                       
MENU_TITLE_GLOW_SCALE = 1.12                     
MENU_TITLE_TRIANGLE_SCALE = 0.82                 
MENU_TITLE_LETTER_SPACING = 0.012                

MENU_MODE_BADGE_BG = (22, 26, 34, 120)          
MENU_MODE_BADGE_BORDER = (120, 200, 255, 110)    
MENU_MODE_BADGE_RADIUS = 10
MENU_MODE_TEXT_COLOR = (225, 230, 240)           

OVER_TITLE_OFFSET_Y = -60            
OVER_SCORE_GAP1 = -10                
OVER_SCORE_GAP2 = 26                 
OVER_INFO_GAP = 60                   
SETTINGS_TITLE_Y_FACTOR = 0.06      
SETTINGS_LIST_Y_START_FACTOR = 0.16  
SETTINGS_ITEM_SPACING = 3            
SETTINGS_HELP_MARGIN_TOP = 18        
SETTINGS_HELP_GAP = 6                
SETTINGS_CENTER_GAP = 12             

# --- HUD top bar -------------------------------------------------------------
TOPBAR_HEIGHT_FACTOR = 0.095                    
TOPBAR_PAD_X_FACTOR = 0.045                     
TOPBAR_UNDERLINE_THICKNESS = 4                  
TOPBAR_UNDERLINE_COLOR = (90, 200, 255)         
TOPBAR_UNDERLINE_SHADOW_COLOR = (0, 0, 0, 140)  
TOPBAR_UNDERLINE_SHADOW_OFFSET = (2, 3)         
TOPBAR_UNDERLINE_SHADOW_EXTRA_THICK = 3         
TOPBAR_UNDERLINE_SHADOW_RADIUS = 2              

CAPSULE_HEAD_RATIO = 0.75                           
SCORE_CAPSULE_WIDTH_FACTOR = 0.50                   
SCORE_CAPSULE_HEIGHT_FACTOR = 0.20                  
SCORE_CAPSULE_BORDER_COLOR = (120, 200, 255, 220)   
SCORE_CAPSULE_BG = (22, 26, 34, 170)                
SCORE_CAPSULE_RADIUS = 26                           
SCORE_CAPSULE_SHADOW = (0, 0, 0, 140)               
SCORE_CAPSULE_SHADOW_OFFSET = (3, 5)                
SCORE_CAPSULE_MIN_HEIGHT_BONUS = 15                 
CAPSULE_DIVIDER_WIDTH_RATIO = 0.80                  
CAPSULE_DIVIDER_THICKNESS   = 1                     

# Life counter colour parameters
LIVES_COLOR = (90, 220, 255)         
LIVES_LOST_ALPHA = 100                
LIVES_RADIUS_MIN = 2                 
LIVES_RADIUS_MAX = 6                 

# Typography defaults (scaled at runtime)
FONT_PATH = str(PKG_DIR / "assets" / "font" / "Orbitron-VariableFont_wght.ttf")
FONT_SIZE_SMALL = 18
FONT_SIZE_MID = 24
FONT_SIZE_BIG = 60
FONT_SIZE_SETTINGS = 26
HUD_LABEL_FONT_SIZE = 22
HUD_VALUE_FONT_SIZE = 40
SCORE_LABEL_FONT_SIZE = 26
SCORE_VALUE_FONT_SIZE = 64
HUD_LABEL_COLOR = (180, 200, 230)   
HUD_VALUE_COLOR = INK               
SCORE_LABEL_COLOR = ACCENT          
SCORE_VALUE_COLOR = INK             





















