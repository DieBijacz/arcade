from __future__ import annotations

import math
import os
import random
import sys
import time
from typing import Dict, List, Optional, Tuple

import pygame

from .config import CFG, persist_windowed_size, save_config
from .constants import *
from .enums import GlitchMode
from .fx import EffectsManager
from .image_store import IMAGES
from .input_queue import InputQueue
from .level_config import apply_levels_from_cfg, ensure_level_exists
from .managers import BannerManager, RuleManager
from .mods import (
    MODS,
    allowed_mod_ids_from_settings,
    modifier_options,
    mods_from_ids,
    normalize_mods_raw,
)
from .models import LEVELS, LevelCfg, Mode, RuleSpec, RuleType, Scene
from .modes import ModeProfile, ModeRegistry
from .music import MusicController
from .settings import clamp_settings, commit_settings, make_runtime_settings
from .settings_defaults import settings_defaults_from_cfg
from .symbols import SYMBOLS, SYMS
from .tutorials import (
    TutorialPlayer,
    build_tutorial_for_speed,
    build_tutorial_for_timed,
    build_tutorial_from_state,
)
from .ui_components import InputRing, PausableCountdown, TimeBar




class Game:

    # ---- Core lifecycle wiring ----

    def __init__(self, screen: pygame.Surface, mode: Mode = Mode.SPEEDUP):
        self.screen = screen
        self.cfg = CFG
        self.images = IMAGES
        self.mode: Mode = mode
        self.scene: Scene = Scene.MENU
        self.tutorial: Optional[TutorialPlayer] = None

        self.w, self.h = self.screen.get_size()
        self.clock = pygame.time.Clock()
        self.timer_timed = PausableCountdown(self.now)  
        self.timer_speed = PausableCountdown(self.now)   

        # --- Window state ---
        self.last_windowed_size = tuple(CFG.get("display", {}).get("windowed_size", WINDOWED_DEFAULT_SIZE))
        self.last_window_size = self.screen.get_size()

        # --- Input debouncing ---
        self.keys_down: set[int] = set()
        self.lock_until_all_released = False
        self.accept_after = 0.0

        # --- Font cache ---
        self.hud_label_font = pygame.font.Font(FONT_PATH, HUD_LABEL_FONT_SIZE)
        self.hud_value_font = pygame.font.Font(FONT_PATH, HUD_VALUE_FONT_SIZE)
        self._font_cache: dict[tuple[str,int,bool,bool], pygame.font.Font] = {}
        self._sysfont_fallback = "arial"

        # --- Background assets ---
        self.bg_img_raw = self._load_background()
        self.bg_img: Optional[pygame.Surface] = None

        # --- Layout & framebuffer ---
        self._recompute_layout()
        self.fb = pygame.Surface((self.w, self.h), pygame.SRCALPHA)

        # Fonts used when the rule banner is centred vs pinned to the HUD
        self.rule_font_center: Optional[pygame.font.Font] = None
        self.rule_font_pinned: Optional[pygame.font.Font] = None
        self.ui_scale = 1.0
        self._rebuild_fonts() 

        # --- Gameplay state ---
        self.level = 1
        self.hits_in_level = 0
        self.level_goal = LEVEL_GOAL_PER_LEVEL
        self.levels_active = LEVELS_ACTIVE_FOR_NOW

        self.score = 0
        self.streak = 0
        self.best_streak = 0 
        self.final_total = 0
        self.is_new_best = False
        self.lives = MAX_LIVES

        self.target: Optional[str] = None
        self.target_time = TARGET_TIME_INITIAL

        self.pause_until = 0.0
        self.symbol_spawn_time = 0.0
        self.highscore = int(CFG.get("highscore", 0))

        # --- Level configuration / ring layout ---
        self.level_cfg: LevelCfg = LEVELS[1]

        # --- Render helpers ---
        self.ring = InputRing(self)
        self.timebar = TimeBar(self)

        # --- Rule / banner managers ---
        self.rules = RuleManager()
        self.banner = BannerManager(RULE_BANNER_IN_SEC, RULE_BANNER_HOLD_SEC, RULE_BANNER_TO_TOP_SEC)
        self.mods_banner = BannerManager(MODS_BANNER_IN_SEC, MODS_BANNER_HOLD_SEC, MODS_BANNER_OUT_SEC)
        self._pending_timed_mods: Optional[list[str]] = None
        self._mods_banner_was_active: bool = False

        # --- Ring state ---
        self.ring_layout = dict(DEFAULT_RING_LAYOUT)
        self._ring_anim_start = self.now()

        # --- Ring rotation animation state ---
        self.rot_anim = {
            "active": False,
            "t0": 0.0,
            "dur": 0.8,          # animation duration
            "spins": 2.0,        # total spins (2.0 equals 720 degrees)
            "swap_at": 0.5,      # point in the animation when layouts swap
            "swapped": False,
            "from_layout": dict(self.ring_layout),
            "to_layout": dict(self.ring_layout),
}

        self.timed_active_mods: list[str] = []
        self.timed_hits_since_roll: int = 0
        self._last_timed_mods: list[str] = []
        self._timed_mods_changed_at: float = 0.0
        
        # --- Memory mode helpers ---
        self.memory_show_icons = True

                self.memory_hide_deadline = 0.0      # scheduled time to hide symbols during memory mode
        self.memory_preview_armed = False    # countdown ready, waiting for a trigger such as banner completion
        self._banner_was_active = False      # detects the trailing edge of the rule banner animation

        self.key_to_pos = {
            pygame.K_UP: "TOP", pygame.K_RIGHT: "RIGHT", pygame.K_LEFT: "LEFT", pygame.K_DOWN: "BOTTOM",
            pygame.K_w: "TOP",  pygame.K_d: "RIGHT",     pygame.K_a: "LEFT",   pygame.K_s: "BOTTOM",
        }
        self.keymap_current: Dict[int, str] = {}
        self._recompute_keymap()

        self.rotation_breaks: set[int] = set()
        self.did_start_rotation = False

        self.instruction_until = 0.0
        self.instruction_text = ""
        self.allow_skip_instruction = True
        self._tutorial_builders = {
            Mode.SPEEDUP: build_tutorial_for_speed,
            Mode.TIMED: build_tutorial_for_timed,
        }

        # Settings scene scratchpad
        self.settings_page = 0  
        self.settings_scroll = 0.0
        self._settings_row_tops: List[Tuple[float, float]] = []  # (y, height) before scroll offset
        self.settings_idx = 0
        self.settings = make_runtime_settings(CFG)

        for k, v in settings_defaults_from_cfg():
            self.settings.setdefault(k, v)
        
        try:
                        apply_levels_from_cfg(CFG)
        except Exception:
            pass
        try:
            self.levels_active = int(CFG.get("levels_active", self.levels_active))
            self.level_table_sel_row = max(1, min(self.levels_active, self.level_table_sel_row))
            self.level_table_sel_col = max(1, min(4, self.level_table_sel_col))
        except Exception:
            pass

        self.settings_focus_table = False
        self.level_table_sel_row = 1          
        self.level_table_sel_col = 1          

        # Effects & transitions
        self.fx = EffectsManager(self.now, glitch_mode=GlitchMode(self.settings.get("glitch_mode", "BOTH")))
        self.exit_dir_pos: Optional[str] = None  # "TOP"|"RIGHT"|"LEFT"|"BOTTOM"
        self.instruction_intro_t = 0.0
        self.instruction_intro_dur = 0.0

        # Music
        self.music_ok = False
        self._ensure_music()

        # Sound effects
        self._preload_audio_assets()

        self.last_window_size = self.screen.get_size()

    def start_game(self) -> None:
        if self.scene is Scene.MENU:
            self._ensure_mode_system_ready()
        self.reset_game_state()

        try:
            self._ensure_mode_system_ready()
            prof = self.mode_registry.current()
            if hasattr(self, "music") and prof.game_music_path:
                self.music.fade_to(prof.game_music_path, ms=prof.crossfade_ms)
        except Exception:
            pass

    def end_game(self) -> None:
        self.scene = Scene.OVER

        self.final_total = int(self.score + self.best_streak)
        self.is_new_best = self.final_total > self.highscore
        if self.is_new_best:
            self.highscore = self.final_total
            CFG["highscore"] = int(self.highscore)
            save_config({"highscore": CFG["highscore"]})

        try:
            self._ensure_mode_system_ready()
            prof = self.mode_registry.current()
            if hasattr(self, "music") and prof.menu_music_path:
                self.music.fade_to(prof.menu_music_path, ms=prof.crossfade_ms)
        except Exception:
            if self.music_ok:
                pygame.mixer.music.fadeout(MUSIC_FADEOUT_MS)

    # ---- Timing utilities ----

    def now(self) -> float:
        return time.time()
  
    def stop_timer(self):
        self.timer_timed.stop()
        self.timer_speed.stop()

    def start_timer(self):
        if self.scene is Scene.GAME:
            if self.mode is Mode.TIMED:
                self.timer_timed.resume()
            elif self.mode is Mode.SPEEDUP:
                self.timer_speed.resume()

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
        self.pause_until = max(self.pause_until, now + EXIT_SLIDE_SEC)
        self.target = None

        self.stop_timer()
        return True

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
        hide_sec = self._memory_hide_seconds()
        self.memory_hide_deadline = self.now() + max(0.1, hide_sec)
        self.memory_preview_armed = False

    def _memory_hide_seconds(self) -> float:
        if self.mode is Mode.TIMED:
            return float(self.settings.get("timed_memory_hide_sec", MEMORY_HIDE_AFTER_SEC))
        return float(self.settings.get("memory_hide_sec", MEMORY_HIDE_AFTER_SEC))

    def _mods_chain_active(self) -> bool:
        now = self.now()
        return self.mods_banner.is_active(now) or self.banner.is_active(now)

    def _timed_slots(self) -> int:
        diff = str(self.settings.get("timed_difficulty", "EASY"))
        return 1 if diff == "EASY" else (2 if diff == "MEDIUM" else 3)

    def _timed_apply_active_mods(self) -> None:
        old = list(self.timed_active_mods)

        self._timed_prune_disallowed()
        self.timed_active_mods = list(dict.fromkeys(self.timed_active_mods))

        self.level_cfg.control_flip_lr_ud = False
        self.level_cfg.memory_mode = False
        self._recompute_keymap()

        any_remap = False
        for mod in mods_from_ids(self.timed_active_mods):
            if isinstance(mod, RemapMod):
                any_remap = True
            mod.apply_runtime_flags(self)

        if not any_remap:
            self.rules.install([])
            self.rules.current_mapping = None

        if "memory" not in self.timed_active_mods:
            self.memory_show_icons = True
            self.memory_hide_deadline = 0.0

        for mod in mods_from_ids(self.timed_active_mods):
            mod.on_mods_applied(self)

        if old != self.timed_active_mods:
            self._last_timed_mods = list(self.timed_active_mods)
            self._timed_mods_changed_at = self.now()

    def _timed_roll_mod(self) -> None:
        if self._mods_chain_active() or (self._pending_timed_mods is not None):
            return

        allowed = self._timed_allowed_pool()
        if not allowed:
            new_set = []
        else:
            slots = min(self._timed_slots(), len(allowed))

            self._timed_prune_disallowed()
            active = list(dict.fromkeys(self.timed_active_mods))

            if len(active) < slots:
                choices = [m for m in allowed if m not in active]
                random.shuffle(choices)
                need = slots - len(active)
                active += choices[:need]
            else:
                old = active.pop(0) if active else None
                choices = [m for m in allowed if m not in active and m != old]
                pick = random.choice(choices) if choices else old
                if pick and pick not in active:
                    active.append(pick)

            new_set = active[:slots]

        self._timed_queue_mod_change(new_set)

    def _timed_allowed_pool(self) -> list[str]:
        return allowed_mod_ids_from_settings(self.settings)

    def _timed_prune_disallowed(self) -> None:
        allowed = set(self._timed_allowed_pool())
        self.timed_active_mods = [m for m in self.timed_active_mods if m in allowed]

    def _timed_fill_to_slots(self) -> None:
        allowed = [m for m in self._timed_allowed_pool()]
        if not allowed:
            self.timed_active_mods = []
            return
        slots = max(0, min(self._timed_slots(), len(allowed)))

        seen = set()
        clean = []
        for m in self.timed_active_mods:
            if m in allowed and m not in seen:
                clean.append(m); seen.add(m)
        self.timed_active_mods = clean[:slots]

        import random as _r
        while len(self.timed_active_mods) < slots:
            choices = [m for m in allowed if m not in self.timed_active_mods]
            if not choices:
                break
            self.timed_active_mods.append(_r.choice(choices))

    def _timed_queue_mod_change(self, new_mods: list[str]) -> None:
        self._pending_timed_mods = list(new_mods or [])
        now = self.now()
        if not self.mods_banner.is_active(now):
            self.mods_banner.start(now, from_pinned=False)
            self.pause_until = max(self.pause_until, now + self.mods_banner.total)
            self.stop_timer()
            gi = float(self.settings.get("glitch_screen_intensity", 0.65))
            self.fx.trigger_glitch(mag=max(0.0, min(1.5, 0.55 * gi)))  

    def _commit_queued_timed_mods(self) -> None:
        if self._pending_timed_mods is None:
            return
        self.timed_active_mods = list(self._pending_timed_mods)
        self._pending_timed_mods = None

        self._timed_apply_active_mods()
        self._timed_mods_changed_at = self.now()

        if "remap" in self.timed_active_mods and self.rules.current_mapping:
            self._start_mapping_banner(from_pinned=False)

    def _ease_linear(self, t: float) -> float:
        return self.fx._ease_linear(t)

    def _ease_in_out(self, t: float) -> float:
        return self.fx._ease_in_out(t)

    def _ease_out_cubic(self, t: float) -> float:
        return self.fx._ease_out_cubic(t)

    def _ease_in_cubic(self, t: float) -> float:
        return self.fx._ease_in_cubic(t)


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

        self.font              = self._font(S(FONT_SIZE_SMALL))
        self.mid               = self._font(S(FONT_SIZE_MID))
        self.big               = self._font(S(FONT_SIZE_BIG))
        self.timer_font        = self._font(S(TIMER_FONT_SIZE))
        self.hud_label_font    = self._font(S(HUD_LABEL_FONT_SIZE))
        self.hud_value_font    = self._font(S(HUD_VALUE_FONT_SIZE))
        self.score_label_font  = self._font(S(SCORE_LABEL_FONT_SIZE))
        self.score_value_font  = self._font(S(SCORE_VALUE_FONT_SIZE))
        self.settings_font     = self._font(S(FONT_SIZE_SETTINGS))

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
    
    def _preload_audio_assets(self) -> None:
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.set_num_channels(16)
        except Exception:
            self.sfx = {}
            return

        self.sfx = {}
        sfx_dir = PKG_DIR / "assets" / "sfx"

        sfx_files = {
            "point":  "sfx_point.wav",
            "wrong":  "sfx_wrong.wav",
            "glitch": "sfx_glitch.wav",
        }
        for key, fname in sfx_files.items():
            path = sfx_dir / fname
            try:
                if path.exists():
                    self.sfx[key] = pygame.mixer.Sound(str(path))
            except Exception:
                pass

        try:
            sfx_vol = float(self.settings.get("sfx_volume", CFG["audio"]["sfx_volume"]))
            for s in self.sfx.values():
                s.set_volume(sfx_vol)
        except Exception:
            pass

        music_dir = PKG_DIR / "assets" / "music"
        music_paths = [
            music_dir / "menu_speedup.ogg",
            music_dir / "game_speedup.ogg",
            music_dir / "menu_timed.ogg",
            music_dir / "game_timed.ogg",
        ]

        try:
            for mp in music_paths:
                if mp.exists():
                    pygame.mixer.music.load(str(mp))
            pygame.mixer.music.stop()
        except Exception:
            pass

    def _ensure_mode_system_ready(self) -> None:
        if hasattr(self, "mode_registry"):
            return

        images_dir = PKG_DIR / "assets" / "images"
        music_dir  = PKG_DIR / "assets" / "music"

        speedup = ModeProfile(
            key=Mode.SPEEDUP,
            label="SPEED-UP",
            order=0,
            menu_bg_path=str(images_dir / "menu_speedup.png"),
            game_bg_path=str(images_dir / "game_speedup.png"),
            menu_music_path=str(music_dir / "menu_speedup.ogg"),
            game_music_path=str(music_dir / "game_speedup.ogg"),
            crossfade_ms=700,
        )
        timed = ModeProfile(
            key=Mode.TIMED,
            label="TIMED",
            order=1,
            menu_bg_path=str(images_dir / "menu_timed.png"),
            game_bg_path=str(images_dir / "game_timed.png"),
            menu_music_path=str(music_dir / "menu_timed.ogg"),
            game_music_path=str(music_dir / "game_timed.ogg"),
            crossfade_ms=700,
        )

        self.mode_registry = ModeRegistry([speedup, timed], initial_key=self.mode)

        vol = float(self.settings.get("music_volume", self.cfg["audio"]["music_volume"]))
        self.music = getattr(self, "music", MusicController(volume=vol))
        self.music.set_volume(vol)

        cur = self.mode_registry.current()
        if cur.menu_music_path:
            self.music.fade_to(cur.menu_music_path, ms=cur.crossfade_ms)

        self._menu_anim = {
            "active": False, "from_idx": 0, "to_idx": 0,
            "t0": 0.0, "dur": 0.35, "dir": +1
        }
        self._glitch_before_slide: Optional[str] = None  

    def _menu_get_bg(self, profile: ModeProfile) -> pygame.Surface:
        w, h = self.w, self.h
        if profile._bg_scaled is not None and profile._bg_cache_key == (w, h):
            return profile._bg_scaled
        raw = IMAGES.load(profile.menu_bg_path) if profile.menu_bg_path else None
        if not raw:
            s = pygame.Surface((w, h))
            s.fill(BG)
            profile._bg_scaled = s
            profile._bg_cache_key = (w, h)
            return s
        rw, rh = raw.get_size()
        scale = max(w / rw, h / rh)
        new_size = (max(1, int(rw * scale)), max(1, int(rh * scale)))
        scaled = pygame.transform.smoothscale(raw, new_size)
        x = (scaled.get_width() - w) // 2
        y = (scaled.get_height() - h) // 2
        cropped = scaled.subsurface(pygame.Rect(x, y, w, h)).copy()
        profile._bg_scaled = cropped
        profile._bg_cache_key = (w, h)
        return cropped

    def _render_menu_background(self) -> None:
        self._ensure_mode_system_ready()
        w, h = self.w, self.h
        out = pygame.Surface((w, h))

        anim = getattr(self, "_menu_anim", {"active": False})
        peek_ratio = 0.0 
        cur = self.mode_registry.current()
        cur_bg = self._menu_get_bg(cur)

        if anim["active"]:
            p = max(0.0, min(1.0, (self.now() - anim["t0"]) / max(1e-6, anim["dur"])))
            pe = self._ease_in_out(p)

            from_p = self.mode_registry.modes[anim["from_idx"]]
            to_p   = self.mode_registry.modes[anim["to_idx"]]
            from_bg = self._menu_get_bg(from_p)
            to_bg   = self._menu_get_bg(to_p)

            dir_ = +1 if anim["dir"] >= 0 else -1
            offset = round(self.w * pe)

            from_x = -offset * dir_
            to_x   = from_x + self.w * dir_

            out.blit(from_bg, (from_x, 0))
            out.blit(to_bg, (to_x, 0))
        else:
            out.blit(cur_bg, (0, 0))
            right_idx = self.mode_registry.next_index(+1)
            if right_idx is not None:
                nxt = self.mode_registry.modes[right_idx]
                nxt_bg = self._menu_get_bg(nxt)
                peek_w = int(w * peek_ratio)
                src = pygame.Rect(nxt_bg.get_width() - peek_w, 0, peek_w, h)
                out.blit(nxt_bg, (w - peek_w, 0), area=src)

        self.bg_img = out

    def _start_menu_mode_transition(self, to_idx: int) -> None:
        if getattr(self, "_menu_anim", {}).get("active", False):
            return
        if not (0 <= to_idx < len(self.mode_registry.modes)):
            return
        from_idx = self.mode_registry.idx
        if to_idx == from_idx:
            return

        self._menu_anim.update({
            "active": True,
            "from_idx": from_idx,
            "to_idx": to_idx,
            "t0": self.now(),
            "dur": 0.3,   
            "dir": +1 if to_idx > from_idx else -1,
        })

        to_profile = self.mode_registry.modes[to_idx]
        if hasattr(self, "music") and to_profile.menu_music_path:
            self.music.fade_to(to_profile.menu_music_path, ms=to_profile.crossfade_ms)

        self._glitch_before_slide = str(self.settings.get("glitch_mode", "BOTH"))
        self.fx.set_glitch_mode(GlitchMode.NONE)

    def _update_menu_mode_transition(self) -> None:
        anim = getattr(self, "_menu_anim", None)
        if not anim or not anim["active"]:
            return
        t = (self.now() - anim["t0"]) / max(1e-6, anim["dur"])
        if t >= 1.0:
            self.mode_registry.set_index(anim["to_idx"])
            new_profile = self.mode_registry.current()
            self.mode = new_profile.key
            anim["active"] = False

            gm = self._glitch_before_slide or "BOTH"
            self._glitch_before_slide = None
            try:
                self.fx.set_glitch_mode(GlitchMode(gm))
            except Exception:
                self.fx.set_glitch_mode(GlitchMode.BOTH)

        self._render_menu_background()


    def _set_windowed_size(self, width: int, height: int) -> None:
        width, height = self._snap_to_aspect(width, height)

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

# ---- Settings ----

    def settings_items(self):
        items: list[tuple[str, str, Optional[str]]] = []

        # 0=BASIC, 1=TIMED, 2=SPEED-UP
        cur_view = "BASIC" if self.settings_page == 0 else ("SPEED-UP" if self.settings_page == 1 else "TIMED")
        items += [("View", cur_view, "settings_page")]

        if self.settings_page == 0:
            # ===== BASIC =====
            items += [
                ("Music volume",  f"{float(self.settings.get('music_volume', CFG['audio']['music_volume'])):.2f}", "music_volume"),
                ("SFX volume",    f"{float(self.settings.get('sfx_volume',   CFG['audio']['sfx_volume'])):.2f}",   "sfx_volume"),
                ("Fullscreen",    "ON" if self.settings.get('fullscreen', CFG['display'].get('fullscreen', True)) else "OFF", "fullscreen"),
                ("Glitch",        self.settings.get('glitch_mode', 'BOTH'), "glitch_mode"),
                ("Glitch intensity", f"{float(self.settings.get('glitch_screen_intensity', 0.65)):.2f}", "glitch_screen_intensity"),
                ("FPS cap",       f"{int(self.settings.get('fps', FPS))}",  "fps"),
                ("Ring palette",  f"{self.settings.get('ring_palette', 'auto')}", "ring_palette"),
                ("High score",    f"{self.highscore}", "highscore"),
            ]
            return items

        if self.settings_page == 1:
            # ===== SPEED-UP =====
            items += [
                ("Initial time",  f"{float(self.settings.get('target_time_initial', TARGET_TIME_INITIAL)):.2f}s",   "target_time_initial"),
                ("Time step",     f"{float(self.settings.get('target_time_step', TARGET_TIME_STEP)):+.2f}s/hit",    "target_time_step"),
                ("Minimum time",  f"{float(self.settings.get('target_time_min', TARGET_TIME_MIN)):.2f}s",           "target_time_min"),
                ("Remap every",   f"{int(self.settings.get('remap_every_hits', RULE_EVERY_HITS))} hits",            "remap_every_hits"),
                ("Rotate every",  f"{int(self.settings.get('spin_every_hits', 5))} hits",                           "spin_every_hits"),
                ("Lives",         f"{int(self.settings.get('lives', MAX_LIVES))}",                                  "lives"),
                ("Levels active", f"{int(self.levels_active)}",                                                     "levels_active"),
                ("Memory hide after", f"{float(self.settings.get('memory_hide_sec', MEMORY_HIDE_AFTER_SEC)):.1f}s", "memory_hide_sec"),
            ]
            return items

        # ===== TIMED =====
        items += [
            ("Difficulty",    f"{self.settings.get('timed_difficulty','EASY')}",                 "timed_difficulty"),
            ("New mod every", f"{int(self.settings.get('timed_mod_every_hits',6))} hits",        "timed_mod_every_hits"),
            ("Initial time",  f"{float(self.settings.get('timed_duration', TIMED_DURATION)):.1f}s", "timed_duration"),
            ("On correct",    f"+{float(self.settings.get('timed_gain', 1.0)):.1f}s",            "timed_gain"),
            ("On wrong",      f"-{float(self.settings.get('timed_penalty', 1.0)):.1f}s",         "timed_penalty"),
            ("Rule bonus",    f"{float(self.settings.get('timed_rule_bonus', ADDITIONAL_RULE_TIME)):.1f}s","timed_rule_bonus"),
            ("Remap every",   f"{int(self.settings.get('timed_remap_every_hits',6))} hits",      "timed_remap_every_hits"),
            ("Rotate every",  f"{int(self.settings.get('timed_spin_every_hits',5))} hits",       "timed_spin_every_hits"),
            ("Memory hide after", f"{float(self.settings.get('timed_memory_hide_sec', MEMORY_HIDE_AFTER_SEC)):.1f}s", "timed_memory_hide_sec"),
            ("- MECHANICS -", "", None),
            ("Remap",     "ON" if self.settings.get("timed_enable_remap", True) else "OFF",      "timed_enable_remap"),
            ("Spin",      "ON" if self.settings.get("timed_enable_spin", True) else "OFF",       "timed_enable_spin"),
            ("Memory",    "ON" if self.settings.get("timed_enable_memory", True) else "OFF",     "timed_enable_memory"),
            ("Inverted",  "ON" if self.settings.get("timed_enable_joystick", True) else "OFF",   "timed_enable_joystick"),
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
        # reserve vertical space for the help footer
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
        else:
            self.open_settings()

    def settings_adjust(self, delta: int) -> None:
        items = self.settings_items()
        key = items[self.settings_idx][2]
        if key is None:
            return

        if key == "timed_difficulty":
            opts = ["EASY", "MEDIUM", "HARD"]
            cur = self.settings.get("timed_difficulty", "EASY")
            i = (opts.index(cur) + delta) % len(opts)
            self.settings["timed_difficulty"] = opts[i]
            self._timed_fill_to_slots()
            self._timed_apply_active_mods()
            return

        if key == "timed_remap_every_hits":
            v = int(self.settings.get("timed_remap_every_hits", 6)) + delta
            self.settings["timed_remap_every_hits"] = max(1, min(20, v))
            if self.mode is Mode.TIMED and "remap" in self.timed_active_mods:
                self.rules.mapping_every_hits = int(self.settings["timed_remap_every_hits"])
            return

        if key == "timed_spin_every_hits":
            v = int(self.settings.get("timed_spin_every_hits", 5)) + delta
            self.settings["timed_spin_every_hits"] = max(1, min(50, v))
            return

        if key == "timed_mod_every_hits":
            v = int(self.settings.get("timed_mod_every_hits", 6)) + delta
            self.settings["timed_mod_every_hits"] = max(1, min(20, v))
            return

        if key in ("timed_enable_remap", "timed_enable_spin", "timed_enable_memory", "timed_enable_joystick"):
            self.settings[key] = not bool(self.settings.get(key, True))
            self._timed_prune_disallowed()
            self._timed_fill_to_slots()
            self._timed_apply_active_mods()
            return

        if key == "settings_page":
            self.settings_page = (self.settings_page + (1 if delta > 0 else -1)) % 3
            self.settings_idx = 0
            self.settings_scroll = 0.0
            self.settings_focus_table = False
            self._ensure_selected_visible()
            gi = float(self.settings.get("glitch_screen_intensity", 0.65))
            self.fx.trigger_glitch(mag=max(0.0, min(1.5, 0.95 * gi)))
            self.fx.trigger_text_glitch()
            return

        if key == "glitch_mode":
            opts = ["NONE", "TEXT", "SCREEN", "BOTH"]
            cur = self.settings.get("glitch_mode", "BOTH")
            i = (opts.index(cur) + delta) % len(opts)
            val = opts[i]
            self.settings["glitch_mode"] = val
            self.fx.set_glitch_mode(GlitchMode(val))
            return

        if key == "glitch_screen_intensity":
            k = float(self.settings.get("glitch_screen_intensity", 0.65))
            k = max(0.0, min(1.0, k + 0.05 * (1 if delta > 0 else -1)))
            self.settings["glitch_screen_intensity"] = k
            return

        if key == "fps":
            caps = [30, 45, 60, 90, 120]
            cur  = int(self.settings.get("fps", FPS))
            try: i = caps.index(cur)
            except ValueError: i = 2
            i = (i + delta) % len(caps)
            self.settings["fps"] = int(caps[i])
            return

        if key == "ring_palette":
            opts = ["auto", "clean-white", "electric-blue", "neon-cyan", "violet-neon", "magenta"]
            cur = self.settings.get("ring_palette", "auto")
            i = (opts.index(cur) + delta) % len(opts)
            self.settings["ring_palette"] = opts[i]
            return

        if key == "remap_every_hits":
            v = int(self.settings.get("remap_every_hits", RULE_EVERY_HITS)) + delta
            v = max(1, min(10, v))
            self.settings["remap_every_hits"] = v
            if hasattr(self, "rules"):
                self.rules.mapping_every_hits = int(v)
            return

        if key == "spin_every_hits":
            v = int(self.settings.get("spin_every_hits", 5)) + delta
            self.settings["spin_every_hits"] = max(1, min(50, v))
            return

        if key and key.startswith("level") and ("_hits" in key or "_color" in key):
            try:
                lid = int(key.split("level",1)[1].split("_",1)[0])
                L = LEVELS.get(lid)
                if L and key.endswith("_hits"):
                    L.hits_required = max(1, min(999, L.hits_required + delta))
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

        if key == "levels_active":
            new_val = int(max(1, min(LEVELS_MAX, int(self.levels_active) + delta)))
            if new_val > self.levels_active:
                for lid in range(self.levels_active + 1, new_val + 1):
                    ensure_level_exists(lid)
            self.levels_active = new_val
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
            "timed_duration": 1.0,
            "timed_gain": 0.1,
            "timed_penalty": 0.1,
            "memory_hide_sec": 0.1,
            "timed_memory_hide_sec": 0.1,
        }.get(key, 0.0)

        if step == 0.0:
            return

        cur = self.settings[key]
        self.settings[key] = (cur + (step * delta)) if isinstance(cur, float) else (cur + delta)
        clamp_settings(self.settings)

        self.settings["timed_duration"] = max(1.0, float(self.settings.get("timed_duration", 60.0)))
        self.settings["timed_gain"]     = max(0.0, float(self.settings.get("timed_gain", 0.0)))
        self.settings["timed_penalty"]  = max(0.0, float(self.settings.get("timed_penalty", 0.0)))

        if key == "memory_hide_sec":
            self.settings["memory_hide_sec"] = max(0.5, float(self.settings["memory_hide_sec"]))
        if key == "timed_memory_hide_sec":
            self.settings["timed_memory_hide_sec"] = max(0.5, float(self.settings["timed_memory_hide_sec"]))

        if key == "music_volume" and self.music_ok:
            pygame.mixer.music.set_volume(float(self.settings["music_volume"]))
        elif key == "sfx_volume":
            v = float(self.settings["sfx_volume"])
            for s in getattr(self, "sfx", {}).values():
                s.set_volume(v)
            try:
                if self.sfx.get("point"):
                    self.sfx["point"].play()
            except Exception:
                pass

    def open_settings(self) -> None:
        self.settings = make_runtime_settings(CFG)

        for k, v in settings_defaults_from_cfg():
            self.settings.setdefault(k, v)
        try:
            self.levels_active = int(CFG.get("levels_active", self.levels_active))
        except Exception:
            pass

        self.settings_idx = 0
        self.settings_move(0)

        gi = float(self.settings.get("glitch_screen_intensity", 0.65))
        self.fx.trigger_glitch(mag=max(0.0, min(1.5, 1.0 * gi)))
        self.scene = Scene.SETTINGS
        self.settings_scroll = 0.0
        self._ensure_selected_visible()

    def settings_save(self) -> None:
        clamp_settings(self.settings)

        payload = commit_settings(
            self.settings,
            CFG=CFG,
            LEVELS=LEVELS,
            TIMED_DURATION=TIMED_DURATION,
            WINDOWED_DEFAULT_SIZE=WINDOWED_DEFAULT_SIZE,
            RULE_EVERY_HITS=int(self.settings.get("remap_every_hits", RULE_EVERY_HITS)),
        )

        # EFFECTS / DISPLAY / AUDIO
        effects = payload.setdefault("effects", {})
        effects["glitch_mode"] = self.settings.get("glitch_mode", "BOTH")
        effects["glitch_screen_intensity"] = float(self.settings.get("glitch_screen_intensity", 0.65))

        disp = payload.setdefault("display", {})
        disp["fps"]        = int(self.settings.get("fps", FPS))
        disp["fullscreen"] = bool(self.settings.get("fullscreen", CFG.get("display", {}).get("fullscreen", True)))
        disp["ring_palette"] = str(self.settings.get("ring_palette", "auto"))

        aud = payload.setdefault("audio", {})
        aud["music_volume"] = float(self.settings.get("music_volume", CFG["audio"]["music_volume"]))
        aud["sfx_volume"]   = float(self.settings.get("sfx_volume",   CFG["audio"]["sfx_volume"]))

        # RULES (SPEED-UP)
        rules = payload.setdefault("rules", {})
        rules["every_hits"]      = int(self.settings.get("remap_every_hits", RULE_EVERY_HITS))
        rules["spin_every_hits"] = int(self.settings.get("spin_every_hits", 5))

        payload["memory_hide_sec"] = float(self.settings.get("memory_hide_sec", MEMORY_HIDE_AFTER_SEC))

        # TIMED
        t = payload.setdefault("timed", {})
        t["duration"]        = float(self.settings.get("timed_duration",   TIMED_DURATION))
        t["gain"]            = float(self.settings.get("timed_gain",       1.0))
        t["penalty"]         = float(self.settings.get("timed_penalty",    1.0))
        t["rule_bonus"]      = float(self.settings.get("timed_rule_bonus", ADDITIONAL_RULE_TIME))
        t["difficulty"]      = str(self.settings.get("timed_difficulty",   "EASY"))
        t["mod_every_hits"]  = int(self.settings.get("timed_mod_every_hits", 6))
        t["allow_remap"]     = bool(self.settings.get("timed_enable_remap", True))
        t["allow_spin"]      = bool(self.settings.get("timed_enable_spin", True))
        t["allow_memory"]    = bool(self.settings.get("timed_enable_memory", True))
        t["allow_joystick"]  = bool(self.settings.get("timed_enable_joystick", True))
        t["remap_every_hits"]= int(self.settings.get("timed_remap_every_hits", 6))
        t["spin_every_hits"] = int(self.settings.get("timed_spin_every_hits", 5))
        t["memory_hide_sec"] = float(self.settings.get("timed_memory_hide_sec", MEMORY_HIDE_AFTER_SEC))

        # Levels active + table
        payload["levels_active"] = int(self.levels_active)
        levels_out: dict[str, dict] = {}
        for lid, L in LEVELS.items():
            levels_out[str(lid)] = {
                "hits": int(getattr(L, "hits_required", LEVEL_GOAL_PER_LEVEL)),
                "mods": list(getattr(L, "modifiers", []))[:3],
            }
        payload["levels"] = levels_out

        save_config(payload)

        def _deep_merge(dst, src):
            for k, v in src.items():
                if isinstance(v, dict) and isinstance(dst.get(k), dict):
                    _deep_merge(dst[k], v)
                else:
                    dst[k] = v
        _deep_merge(CFG, payload)
        apply_levels_from_cfg(CFG)

        if self.music_ok:
            pygame.mixer.music.set_volume(float(self.settings.get("music_volume", CFG["audio"]["music_volume"])))
        for sfx in getattr(self, "sfx", {}).values():
            sfx.set_volume(float(self.settings.get("sfx_volume", CFG["audio"]["sfx_volume"])))

        # fullscreen + UI
        self._set_display_mode(bool(self.settings.get("fullscreen", CFG.get("display", {}).get("fullscreen", True))))
        self._rebuild_fonts()

        gi = float(self.settings.get("glitch_screen_intensity", 0.65))
        self.fx.trigger_glitch(mag=max(0.0, min(1.5, 1.0 * gi)))

        self.scene = Scene.MENU

    def settings_cancel(self) -> None:
        self.fx.trigger_glitch(mag=1.0)
        self.scene = Scene.MENU

    def _apply_modifiers_to_fields(self, L: LevelCfg) -> None:
        raw = normalize_mods_raw((L.modifiers or [])[:3])
        pool_all = MODS.ids()
        resolved: list[str] = []
        for m in raw:
            if m == "random":
                import random as _r
                choices = [x for x in pool_all if x not in resolved]
                pick = _r.choice(choices or pool_all)
                resolved.append(pick)
            else:
                resolved.append(m)

        setattr(L, "_mods_resolved", resolved[:3])
        L.rules = []
        L.memory_mode = False
        L.control_flip_lr_ud = False
        for mod in mods_from_ids(resolved):
            mod.on_apply_level(self, L)

    def _set_level_mod_slot(self, lid: int, slot_idx: int, direction: int) -> None:
        L = LEVELS.get(lid)
        if not L:
            return

        mods = (L.modifiers or [])[:]
        while len(mods) < 3:
            mods.append("-")
        mods = normalize_mods_raw(mods)
        cur = mods[slot_idx]
        opts = modifier_options()[:]  
        i = opts.index(cur) if cur in opts else 0

        fixed = set(MODS.ids())
        for _ in range(len(opts)):
            i = (i + direction) % len(opts)
            cand = opts[i]
            if cand in ("-", "random"):
                mods[slot_idx] = cand
                break
            others = [mods[j] for j in range(3) if j != slot_idx]
            if cand not in others:
                mods[slot_idx] = cand
                break

        L.modifiers = normalize_mods_raw(mods)
        self._apply_modifiers_to_fields(L)


    def reset_game_state(self) -> None:
        try:
            self.levels_active = int(CFG.get("levels_active", self.levels_active))
        except Exception:
            pass

        self.timer_timed.reset()
        self.timer_speed.reset()

        self.level = 1
        self.hits_in_level = 0
        self.level_goal = LEVELS[1].hits_required
        self.score = 0
        self.streak = 0
        self.best_streak = 0
        self.final_total = 0
        self.is_new_best = False
        self.lives = int(self.settings.get("lives", MAX_LIVES))

        self.rules.install([])
        self.rules.current_mapping = None
        self.target = None
        self.target_time = float(self.settings.get("target_time_initial", TARGET_TIME_INITIAL))
        self.symbol_spawn_time = 0.0
        self.pause_until = 0.0

        self.timed_active_mods = []
        self.timed_hits_since_roll = 0

        # input mapping / ring state reset
        self.level_cfg.control_flip_lr_ud = False
        self.level_cfg.memory_mode = False
        self.ring_layout = dict(DEFAULT_RING_LAYOUT)
        self._recompute_keymap()

        self.scene = Scene.INSTRUCTION
        self.instruction_text = str(self.mode.name)
        self.instruction_until = float('inf')
        self.banner.active_until = 0.0
        self.mods_banner.active_until = 0.0

        if self.mode is Mode.TIMED:
            self._timed_fill_to_slots()  # populate modifier slots based on difficulty
            self._timed_apply_active_mods()  # install mods/rules without triggering the remap banner
            self.tutorial = build_tutorial_from_state(self, mods=self.timed_active_mods, mapping=self.rules.current_mapping)
        else:
            self.apply_level(1)
            return

        self.instruction_intro_t = self.now()
        self.instruction_intro_dur = float(INSTRUCTION_FADE_IN_SEC)

    def apply_level(self, lvl: int) -> None:
        self.level_cfg = LEVELS.get(lvl, LEVELS[max(LEVELS.keys())])
        self.level_goal = int(max(1, self.level_cfg.hits_required))

        self.rules.install([])
        self._apply_modifiers_to_fields(self.level_cfg)
        self.memory_show_icons = True

        self.instruction_text = f"LEVEL {lvl}"
        self.instruction_until = float('inf')
        self.scene = Scene.INSTRUCTION

        resolved = list(getattr(self.level_cfg, "_mods_resolved", self.level_cfg.modifiers or []))
        self.tutorial = build_tutorial_from_state(self, mods=resolved, mapping=None)

        self.instruction_intro_t = self.now()
        self.instruction_intro_dur = float(INSTRUCTION_FADE_IN_SEC)

        resolved_mods = getattr(self.level_cfg, "_mods_resolved", self.level_cfg.modifiers or [])
        for mod in mods_from_ids(resolved_mods):
            mod.on_level_start(self)

        if self.level_cfg.memory_mode:
            self.memory_show_icons = True

        self._recompute_keymap()

    def level_up(self) -> None:
        if self.level < self.levels_active:
            self.level += 1
            self.hits_in_level = 0
            self.apply_level(self.level) 

    def new_target(self) -> None:
        prev = self.target
        choices = [s for s in SYMS if s != prev] if prev else SYMS
        self.target = random.choice(choices)
        self.symbol_spawn_time = self.now()
        self.fx.stop_pulse('symbol')
        self.fx.stop_pulse('timer')

        if self.mode is Mode.SPEEDUP and self.scene is Scene.GAME:
            self.timer_speed.start(self.target_time)

    def _start_mapping_banner(self, from_pinned: bool = False) -> None:
        now = self.now()
        grant_bonus = (self.mode is Mode.TIMED) and (not self.banner.is_active(now))
        self.banner.start(now, from_pinned=from_pinned)
        self.pause_until = max(self.pause_until, now + self.banner.total)
        if grant_bonus:
            bonus = float(self.settings.get("timed_rule_bonus", ADDITIONAL_RULE_TIME))
            self.timer_timed.set(self.timer_timed.get() + max(0.0, bonus))
        if self.level_cfg.memory_mode:
            self.memory_preview_armed = True
            self.memory_hide_deadline = 0.0
        self.stop_timer()

    def _enter_gameplay_after_instruction(self) -> None:
        self.scene = Scene.GAME
        self.tutorial = None
        self.banner.active_until = 0.0
        self.mods_banner.active_until = 0.0

        if self.level_cfg.memory_mode:
            self.memory_show_icons = True
            self.memory_hide_deadline = 0.0
            self.memory_preview_armed = True

        if self.mode is Mode.SPEEDUP:
            self.rules.install(self.level_cfg.rules)
            mapping_spec = next((s for s in (self.level_cfg.rules or [])
                                if s.type is RuleType.MAPPING and s.banner_on_level_start), None)
            if mapping_spec:
                self.rules.roll_mapping(SYMS)
                self._start_mapping_banner(from_pinned=False)
            else:
                if self.level_cfg.memory_mode and self.memory_preview_armed:
                    self._memory_start_preview(reset_moves=False, force_unhide=False)
        else:
            if "remap" in self.timed_active_mods and self.rules.current_mapping:
                self._start_mapping_banner(from_pinned=False)

        if not self.banner.is_active(self.now()) and not self.rot_anim.get("active"):
            self.new_target()
        else:
            self.target = None

        if self.mode is Mode.TIMED:
            self.timer_timed.start(float(self.settings.get("timed_duration", TIMED_DURATION)))
        elif self.mode is Mode.SPEEDUP and self.target:
            self.timer_speed.start(self.target_time)

    def _cleanup_exit_slide_if_ready(self) -> None:
        if not self.exit_dir_pos:
            return
        if self.fx.is_exit_active():
            return

        self.fx.clear_exit()
        self.exit_dir_pos = None

        if self.rot_anim.get("active"):
            return
        if self.scene is Scene.GAME and not self.banner.is_active(self.now()):
            self.new_target()


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
            if event.key in (pygame.K_ESCAPE, pygame.K_q):
                pygame.quit(); sys.exit(0)

            if event.key == pygame.K_o:
                self.toggle_settings()
                return

            if self.scene is Scene.MENU:
                self._ensure_mode_system_ready()
                if event.key == pygame.K_RETURN:
                    self.start_game(); return
                if event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                    delta = -1 if event.key == pygame.K_LEFT else +1
                    to_idx = self.mode_registry.next_index(delta)
                    if to_idx is not None:
                        self._start_menu_mode_transition(to_idx)
                    return

            elif self.scene is Scene.OVER:
                if event.key == pygame.K_SPACE:
                    self.start_game(); return

            elif self.scene is Scene.SETTINGS:
                if event.key == pygame.K_RETURN:
                    if not self.settings_focus_table:
                        items = self.settings_items()
                        label, value, key = items[self.settings_idx]
                        if key == "highscore" and self.highscore != 0:
                            self.highscore = 0
                            CFG["highscore"] = 0
                            save_config({"highscore": 0})
                            return
                    self.settings_save()
                    return

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
                            self._set_level_mod_slot(lid, col - 2, delta)
                    else:
                        self.settings_adjust(delta)
                    return

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
                            if self.settings_page == 1:
                                self.settings_focus_table = True
                                self.level_table_sel_row = 1
                                self.level_table_sel_col = 1
                                self._ensure_selected_visible()
                        else:
                            self.settings_move(+1)
                        return

                if event.key == pygame.K_UP:
                    if self.settings_focus_table:
                        if self.level_table_sel_col > 1:
                            self.level_table_sel_col -= 1
                        else:
                            if self.level_table_sel_row > 1:
                                self.level_table_sel_row -= 1
                                self.level_table_sel_col = 4
                            else:
                                self.settings_focus_table = False
                                self.settings_idx = self._last_editable_settings_idx()
                        return
                    else:
                        self.settings_move(-1)
                        return

            elif self.scene is Scene.INSTRUCTION:
                if event.key in (pygame.K_RETURN, pygame.K_SPACE) or event.key in self.key_to_pos:
                    self._enter_gameplay_after_instruction()
                    return

            self.keys_down.add(event.key)
            name = self.keymap_current.get(event.key)
            if name:
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

        required = self.rules.apply(self.target)
        if name == required:
            self.streak += 1
            if self.streak > self.best_streak:
                self.best_streak = self.streak
            self.score += 1

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
                gain = float(self.settings.get("timed_gain", 1.0))
                self.timer_timed.set(self.timer_timed.get() + gain)

                self.timed_hits_since_roll += 1
                every = int(self.settings.get("timed_mod_every_hits", 6))
                if self.timed_hits_since_roll >= max(1, every) and not self._mods_chain_active():
                    self.timed_hits_since_roll = 0
                    self._timed_roll_mod()

            if self.mode is Mode.SPEEDUP:
                step = float(self.settings.get("target_time_step", TARGET_TIME_STEP))
                tmin = float(self.settings.get("target_time_min", TARGET_TIME_MIN))
                self.target_time = max(tmin, self.target_time + step)

            if self.mode is Mode.TIMED:
                for mod in mods_from_ids(self.timed_active_mods):
                    mod.on_correct(self)
            else:
                resolved = getattr(self.level_cfg, "_mods_resolved", self.level_cfg.modifiers or [])
                for mod in mods_from_ids(resolved):
                    mod.on_correct(self)

            if self.mode is Mode.SPEEDUP and self.hits_in_level >= self.level_goal:
                self.pause_until = 0.0
                self.banner.active_until = 0.0
                self.mods_banner.active_until = 0.0
                try:
                    self.rot_anim["active"] = False
                    self.rot_anim["swapped"] = True
                except Exception:
                    pass
                self.fx.clear_exit()
                self.exit_dir_pos = None

                self.level_up()
                if self.scene is Scene.INSTRUCTION:
                    self.target = None
                    self.fx.clear_exit()
                    self.exit_dir_pos = None
                    self._lock_inputs()
                    return

            if not self._try_start_exit_slide(required):
                self.new_target()
            return

        if self.sfx.get("wrong"): self.sfx["wrong"].play()
        if self.rules.current_mapping and self.target == self.rules.current_mapping[0]:
            self.fx.trigger_pulse_banner()
        self.streak = 0
        self.fx.trigger_shake()

        gi = float(self.settings.get("glitch_screen_intensity", 0.65))
        self.fx.trigger_glitch(mag=max(0.0, min(1.5, 1.0 * gi)))

        if self.mode is Mode.TIMED:
            pen = float(self.settings.get("timed_penalty", 1.0))
            self.timer_timed.set(self.timer_timed.get() - pen)
            if self.timer_timed.expired():
                self.end_game()
        else:
            if self.lives_enabled():
                self.lives -= 1
                if self.lives <= 0:
                    self.end_game()

    def update(self, iq: InputQueue) -> None:
        now = self.now()
        self.fx.maybe_schedule_text_glitch()

        if self.scene is Scene.MENU:
            self._ensure_mode_system_ready()
            self._update_menu_mode_transition()
            if not getattr(self, "_menu_anim", {}).get("active", False):
                self._render_menu_background()
            _ = iq.pop_all()
            return

        banner_active = self.banner.is_active(now)
        if self._banner_was_active and not banner_active:
            if self.level_cfg.memory_mode and self.memory_preview_armed:
                self._memory_start_preview(reset_moves=False, force_unhide=False)
        self._banner_was_active = banner_active

        mods_active = self.mods_banner.is_active(now)
        if getattr(self, "_mods_banner_was_active", False) and not mods_active:
            self._commit_queued_timed_mods()
        self._mods_banner_was_active = mods_active

        if (not banner_active and not mods_active
            and not self.rot_anim.get("active", False)
            and self.rot_anim.get("pending") is not None
            and now >= self.pause_until):
            q = self.rot_anim.pop("pending", None)
            if q:
                self.start_ring_rotation(dur=q["dur"], spins=q["spins"], swap_at=q["swap_at"])

        paused = self.mods_banner.is_active(now) or banner_active or (now < self.pause_until)
        if paused:
            self.stop_timer()
            return
        else:
            self.start_timer()

        if (self.scene is Scene.GAME 
            and self.target is None 
            and not self.mods_banner.is_active(now)
            and not self.banner.is_active(now) 
            and not self.rot_anim.get("active", False) 
            and now >= self.pause_until):
            self.new_target()

        # --- Pulse animation for symbol and timer (SPEEDUP) ---
        if (self.scene is Scene.GAME and self.mode is Mode.SPEEDUP
            and self.target is not None and self.target_time > 0):
            remaining = self.timer_speed.get()
            left_ratio = remaining / max(1e-6, self.target_time)
            if left_ratio <= 0.5:
                if not self.fx.is_pulse_active('symbol'):
                    self.fx.trigger_pulse_symbol()
                if not self.fx.is_pulse_active('timer'):
                    self.fx.trigger_pulse('timer')

        if self.mode is Mode.TIMED and self.scene is Scene.GAME and self.timer_timed.expired():
            self.end_game()
            return

        # SPEEDUP: timeout on the current target
        if (self.mode is Mode.SPEEDUP
            and self.scene is Scene.GAME
            and self.target is not None
            and self.timer_speed.expired()):
            if self.lives_enabled():
                self.lives -= 1
            self.streak = 0
            gi = float(self.settings.get("glitch_screen_intensity", 0.65))
            self.fx.trigger_glitch(mag=max(0.0, min(1.5, 1.0 * gi)))
            if self.lives <= 0:
                self.end_game()
                return
            self.new_target()

        # MEMORY: hide symbols once the timer expires
        if self.level_cfg.memory_mode and self.memory_show_icons:
            if self.memory_hide_deadline > 0.0 and now >= self.memory_hide_deadline:
                self.memory_show_icons = False

        self._cleanup_exit_slide_if_ready()

        for n in iq.pop_all():
            self.handle_input_symbol(n)

# ---- Rendering ----

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
        border_w: int = 1,
    ) -> pygame.Rect:
        fnt = font or self.font
        t_surf = fnt.render(text, True, text_color)
        w, h = t_surf.get_width() + pad * 2, t_surf.get_height() + pad * 2

        chip = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(chip, bg, chip.get_rect(), border_radius=radius)
        pygame.draw.rect(chip, border, chip.get_rect(), width=border_w, border_radius=radius)

        shadow = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 120), shadow.get_rect(), border_radius=radius + 2)
        self.screen.blit(shadow, (x + 3, y + 4))

        chip.blit(t_surf, (pad, pad))
        self.screen.blit(chip, (x, y))
        return pygame.Rect(x, y, w, h)

    def _draw_lives_footer(self, footer: pygame.Rect) -> None:
        if not self.lives_enabled():
            return

        total_lives = int(self.settings.get("lives", MAX_LIVES))
        total_lives = max(0, total_lives)
        if total_lives <= 0:
            return

        alive = max(0, min(int(self.lives), total_lives))
        lost = max(0, total_lives - alive)

        radius = max(LIVES_RADIUS_MIN, min(LIVES_RADIUS_MAX, footer.height // 4))
        gap = max(6, radius * 2)
        dot_w = radius * 2
        total_w = total_lives * dot_w + (total_lives - 1) * gap

        x = footer.centerx - total_w // 2
        cy = footer.centery

        def _blit_circle(col_rgba, cx):
            d = dot_w
            s = pygame.Surface((d, d), pygame.SRCALPHA)
            pygame.draw.circle(s, col_rgba, (radius, radius), radius)
            self.screen.blit(s, (cx, cy - radius))

        for i in range(total_lives):
            cx = x + i * (dot_w + gap)
            if i < alive:
                _blit_circle((*LIVES_COLOR, 230), cx)  
            else:
                _blit_circle((*LIVES_COLOR, max(0, min(255, LIVES_LOST_ALPHA))), cx)  

    def _draw_mod_chip(self, tag: str, x: int, y: int, *, scale: float = 1.0) -> pygame.Rect:
        label = ("INVERTED" if tag == "joystick" else tag).upper()
        col_key = "invert" if tag == "joystick" else tag
        col = MOD_COLOR.get(col_key, INK)
        pad_x = int(self.px(8) * scale)
        pad_y = int(self.px(4) * scale)
        tw, th = self.font.size(label)
        w, h = int(tw * scale) + pad_x * 2, int(th * scale) + pad_y * 2
        rect = pygame.Rect(x, y, w, h)
        self._draw_round_rect(
            self.screen, rect, (20, 22, 30, 160),
            border=(*col, 220), border_w=1, radius=int(self.px(10) * scale)
        )
        self.draw_text(
            label, pos=(x + pad_x, y + pad_y),
            font=self.font, color=col, shadow=True, glitch=False, scale=scale
        )
        return rect

    def _draw_timed_mod_chips(self, footer: pygame.Rect) -> None:
        if self.mode is not Mode.TIMED or self.scene is not Scene.GAME:
            return
        mods = list(self.timed_active_mods)
        if not mods:
            return

        scale = 1.0
        if self._timed_mods_changed_at > 0.0:
            t = self.now() - self._timed_mods_changed_at
            if t <= 0.9:
                k = max(0.0, min(1.0, t / 0.9))
                scale = 1.0 + (1.14 - 1.0) * (1.0 - (1.0 - k) ** 3)
            else:
                self._timed_mods_changed_at = 0.0

        gap = self.px(6)

        def sizes_for(s: float) -> list[tuple[int, int]]:
            out = []
            for m in mods:
                label = ("INVERTED" if m == "joystick" else m).upper()
                tw, th = self.font.size(label)
                padx = int(self.px(8) * s)
                pady = int(self.px(4) * s)
                w = int(tw * s) + padx * 2
                h = int(th * s) + pady * 2
                out.append((w, h))
            return out

        sizes = sizes_for(scale)
        total_w = sum(w for w, _ in sizes) + gap * (len(sizes) - 1)

        if total_w > footer.width:
            k = footer.width / max(1, total_w)
            scale = max(0.72, min(scale, k))
            sizes = sizes_for(scale)
            total_w = sum(w for w, _ in sizes) + gap * (len(sizes) - 1)

        # allow wrapping to two lines if needed
        two_rows = total_w > footer.width

        def draw_row(row_items: list[tuple[str, int, int]], y: int) -> None:
            row_w = sum(w for _, w, _ in row_items) + gap * (len(row_items) - 1)
            x = footer.centerx - row_w // 2
            for tag, w, _h in row_items:
                self._draw_mod_chip(tag, x, y, scale=scale)
                x += w + gap

        labels = [m for m in mods]

        if not two_rows:
            row = list(zip(labels, [w for w, _ in sizes], [h for _, h in sizes]))
            hmax = max((h for _, _, h in row), default=0)
            y = footer.centery - hmax // 2
            draw_row(row, y)
        else:
            mid = (len(labels) + 1) // 2
            sizes1, sizes2 = sizes[:mid], sizes[mid:]
            row1 = list(zip(labels[:mid], [w for w, _ in sizes1], [h for _, h in sizes1]))
            row2 = list(zip(labels[mid:],   [w for w, _ in sizes2], [h for _, h in sizes2]))
            h1 = max((h for _, _, h in row1), default=0)
            y1 = footer.top + max(0, (footer.height - h1 * 2 - self.px(4)) // 2)
            y2 = y1 + h1 + self.px(4)
            draw_row(row1, y1)
            draw_row(row2, y2)

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
            return max(1, int(self.px(v) * scale))

        base_col_w = [S(90), S(120), S(170), S(170), S(170)]
        base_table_w = sum(base_col_w)

        side_pad = int(self.w * 0.01)
        avail_w = max(1, self.w - side_pad * 2)

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

            cell = pygame.Rect(cx, y, col_w[0], row_h)
            txt = str(row)
            tw, th = self.font.size(txt)
            self.draw_text(txt,
                        pos=(cell.centerx - int(tw*scale)/2, cell.centery - int(th*scale)/2),
                        color=INK, font=self.font, shadow=True, glitch=False, scale=scale)
            self._level_table_cells[(row, 0)] = cell
            cx += col_w[0]

            cell = pygame.Rect(cx, y, col_w[1], row_h)
            pts = str(getattr(L, "hits_required", 15))
            tw, th = self.font.size(pts)
            self.draw_text(pts,
                        pos=(cell.centerx - int(tw*scale)/2, cell.centery - int(th*scale)/2),
                        color=INK, font=self.font, shadow=True, glitch=False, scale=scale)
            self._level_table_cells[(row, 1)] = cell
            cx += col_w[1]

            mods = (L.modifiers or [])[:]
            while len(mods) < 3: mods.append("-")
            for c in range(3):
                cell = pygame.Rect(cx, y, col_w[2 + c], row_h)
                tag = mods[c]
                if tag == "-":
                    m = "-"
                    tw, th = self.font.size(m)
                    self.draw_text(m,
                                pos=(cell.centerx - int(tw*scale)/2, cell.centery - int(th*scale)/2),
                                color=(170,180,190), font=self.font, shadow=True, glitch=False, scale=scale)
                else:
                    label = ("INVERTED" if tag == "joystick" else tag).upper()
                    pad_x = int(self.px(8) * scale)
                    pad_y = int(self.px(4) * scale)
                    tw, th = self.font.size(label)
                    w = int(tw * scale) + pad_x * 2
                    h = int(th * scale) + pad_y * 2
                    chip_x = int(cell.centerx - w/2)
                    chip_y = int(cell.centery - h/2)
                    self._draw_mod_chip(tag, chip_x, chip_y, scale=scale)
                self._level_table_cells[(row, 2 + c)] = cell
                cx += col_w[2 + c]

            if self.settings_focus_table and row == self.level_table_sel_row:
                sel = self._level_table_cells.get((row, self.level_table_sel_col))
                if sel:
                    self._draw_cell_underline(sel, inset_px=S(6), thickness=S(3))

            y += row_h + S(6)

        legend = "Legend: remap (magenta) - spin (gold) - memory (red) - inverted joystick (green) - RANDOM (cyan)"
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
        for i in range(passes):
            k = 1.0 + (scale - 1.0) * (i + 1) / passes
            sw = max(1, int(bw * k))
            sh = max(1, int(bh * k))
            s = pygame.transform.smoothscale(base, (sw, sh))
            tint = pygame.Surface((sw, sh), pygame.SRCALPHA)
            tint.fill(color)
            s.blit(tint, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            dx = (glow_w - sw) // 2
            dy = (glow_h - sh) // 2
            out.blit(s, (dx, dy), special_flags=pygame.BLEND_PREMULTIPLIED)
        return out

    def _render_title_remap_minimal(self) -> pygame.Surface:
        left_surf  = self.big.render("REM", True, MENU_TITLE_PRIMARY_COLOR)
        right_surf = self.big.render("P",   True, MENU_TITLE_PRIMARY_COLOR)

        H = max(left_surf.get_height(), right_surf.get_height())

        tri_h = int(H * MENU_TITLE_TRIANGLE_SCALE)
        tri_w = int(tri_h * 0.9)
        thickness = max(2, int(SYMBOL_DRAW_THICKNESS * (H / self.big.get_height())))

        gap = int(self.w * MENU_TITLE_LETTER_SPACING)

        total_w = left_surf.get_width() + gap + tri_w + gap + right_surf.get_width()
        total_h = H
        title = pygame.Surface((total_w, total_h), pygame.SRCALPHA)

        x = 0
        title.blit(self._shadow_text(left_surf), (x + 2, 2))
        title.blit(left_surf, (x, 0))
        x += left_surf.get_width() + gap

        tri_rect = pygame.Rect(0, 0, tri_w, tri_h)
        tri_rect.midbottom = (x + tri_w // 2, total_h)
        a = (tri_rect.centerx, tri_rect.top)
        b = (tri_rect.left, tri_rect.bottom)
        c = (tri_rect.right, tri_rect.bottom)
        pygame.draw.polygon(title, MENU_TITLE_TRIANGLE_COLOR, [a, b, c], thickness)
        x += tri_w + gap

        title.blit(self._shadow_text(right_surf), (x + 2, 2))
        title.blit(right_surf, (x, 0))

        t = self.now()
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

    def _draw_mods_banner_anim(self) -> None:
        now = self.now()
        phase, p = self.mods_banner.phase(now)

        mid_y = int(self.h * 0.30)
        if phase == "in":
            k = self._ease_out_cubic(p)
            y = int(-self.h * 0.35 + (mid_y + self.h * 0.35) * k)
            scale = 0.92 + 0.08 * k
        elif phase == "hold":
            y = mid_y
            scale = 1.0
        else:  # out
            k = self._ease_out_cubic(p)
            pinned_y = int(getattr(self, "_rule_pinned_y", self.topbar_rect.bottom + self.px(12)))
            y = int(mid_y + (pinned_y - mid_y) * k)
            scale = 1.0 - 0.08 * k

        title_surf = self.rule_font_center.render(MODS_BANNER_TITLE, True, ACCENT)
        tw, th = title_surf.get_size()

        mods = list(self._pending_timed_mods if (self._pending_timed_mods is not None) else self.timed_active_mods)
        label = ", ".join(("INVERTED" if m=="joystick" else m).upper() for m in mods) or "NONE"

        info = f"for next {int(self.settings.get('timed_mod_every_hits',6))} hits"
        info_surf = self.mid.render(info, True, (200,210,225))
        lw, lh = self.font.size(label)
        label_surf = self.mid.render(label, True, INK)

        pad = self.px(18)
        inner_w = max(tw, label_surf.get_width(), info_surf.get_width())
        inner_h = th + self.px(10) + label_surf.get_height() + self.px(8) + info_surf.get_height()
        pw = int(max(inner_w + pad*2, self.w * 0.9) * scale)
        ph = int((inner_h + pad*2) * scale)

        panel = pygame.Surface((pw, ph), pygame.SRCALPHA)
        shadow = pygame.Surface((pw, ph), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0,0,0,120), shadow.get_rect(), border_radius=RULE_PANEL_RADIUS+2)
        pygame.draw.rect(panel, RULE_PANEL_BG, panel.get_rect(), border_radius=RULE_PANEL_RADIUS)
        pygame.draw.rect(panel, RULE_PANEL_BORDER, panel.get_rect(), width=RULE_PANEL_BORDER_W, border_radius=RULE_PANEL_RADIUS)

        cx = pw//2
        y0 = pad
        panel.blit(title_surf, (cx - tw//2, y0)); y0 += th + self.px(10)
        panel.blit(label_surf, (cx - label_surf.get_width()//2, y0)); y0 += label_surf.get_height() + self.px(8)
        panel.blit(info_surf, (cx - info_surf.get_width()//2, y0))

        px = (self.w - pw)//2
        self.screen.blit(shadow, (px + 3, y + 5))
        self.screen.blit(panel, (px, y))

    def _draw_underline_segment_with_shadow(self, x1: int, x2: int, y: int, th: int, col) -> None:
        if x2 < x1:
            x1, x2 = x2, x1
        sx, sy = TOPBAR_UNDERLINE_SHADOW_OFFSET
        shadow_h = th + TOPBAR_UNDERLINE_SHADOW_EXTRA_THICK
        shadow_rect = pygame.Rect(x1 + sx, y - shadow_h // 2 + sy, x2 - x1, shadow_h)
        pygame.draw.rect(self.screen, TOPBAR_UNDERLINE_SHADOW_COLOR, shadow_rect,
                        border_radius=TOPBAR_UNDERLINE_SHADOW_RADIUS)
        pygame.draw.line(self.screen, col, (x1, y), (x2, y), th)

    def _draw_hud(self) -> None:
        top_bg = pygame.Surface((self.topbar_rect.width, self.topbar_rect.height), pygame.SRCALPHA)
        top_bg.fill(SCORE_CAPSULE_BG)
        self.screen.blit(top_bg, self.topbar_rect.topleft)

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

        # --- Streak panel (left) ---
        pad_x = int(self.w * TOPBAR_PAD_X_FACTOR)
        left_block = pygame.Rect(
            pad_x, self.topbar_rect.top,
            max(1, cap.left - pad_x * 2),
            self.topbar_rect.height,
        )
        lab = self.draw_text("STREAK", color=HUD_LABEL_COLOR, font=self.hud_label_font, shadow=True)
        label_x = left_block.centerx - lab.get_width() // 2
        label_y = left_block.centery - lab.get_height() - 2
        self.screen.blit(lab, (label_x, label_y))
        scale = self.fx.pulse_scale('streak')
        val = self.draw_text(str(self.streak), color=HUD_VALUE_COLOR, font=self.hud_value_font, shadow=True, scale=scale)
        vx = left_block.centerx - val.get_width() // 2
        vy = label_y + lab.get_height() + 2
        self.screen.blit(val, (vx, vy))

        # --- High-score panel (right) ---
        right_block = pygame.Rect(
            cap.right + pad_x, self.topbar_rect.top,
            max(1, self.w - pad_x - (cap.right + pad_x)),
            self.topbar_rect.height,
        )
        hs_label_color = (255, 230, 140) if self.score > self.highscore else HUD_LABEL_COLOR
        self._draw_label_value_vstack_center(
            label="HIGHSCORE",
            value=str(self.highscore),
            anchor_rect=right_block,
            label_color=hs_label_color,
            value_color=HUD_VALUE_COLOR,
        )

        sx, sy = SCORE_CAPSULE_SHADOW_OFFSET
        shadow_rect = cap.move(sx, sy)
        self._draw_round_rect(self.screen, shadow_rect, SCORE_CAPSULE_SHADOW, radius=SCORE_CAPSULE_RADIUS + 2)
        self._draw_round_rect(
            self.screen, cap, SCORE_CAPSULE_BG,
            border=SCORE_CAPSULE_BORDER_COLOR, border_w=2, radius=SCORE_CAPSULE_RADIUS
        )

        pad_in_x = self.px(12)
        pad_in_y = self.px(10)
        inner = cap.inflate(-pad_in_x * 2, -pad_in_y * 2)

        head_h = int(inner.height * CAPSULE_HEAD_RATIO)
        head_rect = pygame.Rect(inner.left, inner.top, inner.width, max(1, head_h))

        gap = 2
        label_h_fix = self.score_label_font.get_height()
        value_h_fix = self.score_value_font.get_height()
        block_h_fix = label_h_fix + gap + value_h_fix

        # vertically centre the [label + value] block within head_rect
        block_top = head_rect.top + max(0, (head_rect.height - block_h_fix) // 2)

        # 1) label "SCORE" (no scaling)
        label_surf = self.score_label_font.render("SCORE", True, SCORE_LABEL_COLOR)
        self.screen.blit(label_surf, (head_rect.centerx - label_surf.get_width() // 2, block_top))

        value_rect = pygame.Rect(head_rect.left, block_top + label_h_fix + gap, head_rect.width, value_h_fix)
        score_val_surf = self.score_value_font.render(str(self.score), True, SCORE_VALUE_COLOR)
        pulse_scale = self.fx.pulse_scale('score')
        if abs(pulse_scale - 1.0) > 1e-3:
            sw, sh = score_val_surf.get_size()
            score_val_surf = pygame.transform.smoothscale(
                score_val_surf,
                (max(1, int(sw * pulse_scale)), max(1, int(sh * pulse_scale)))
            )
        self.screen.blit(
            score_val_surf,
            (value_rect.centerx - score_val_surf.get_width() // 2,
            value_rect.centery - score_val_surf.get_height() // 2)
        )

        footer_top = head_rect.bottom
        footer_h   = max(1, inner.bottom - footer_top)
        footer     = pygame.Rect(inner.left, footer_top, inner.width, footer_h)

        sep_w = int(inner.width * CAPSULE_DIVIDER_WIDTH_RATIO)
        sep_x1 = inner.centerx - sep_w // 2
        sep_x2 = sep_x1 + sep_w
        sep_y  = footer.top + self.px(6)
        pygame.draw.line(self.screen, (120, 200, 255), (sep_x1, sep_y), (sep_x2, sep_y), max(1, CAPSULE_DIVIDER_THICKNESS))

        content_top = sep_y + CAPSULE_DIVIDER_THICKNESS + self.px(6)
        footer = pygame.Rect(inner.left, content_top, inner.width, max(0, inner.bottom - content_top))

        if self.mode is Mode.TIMED:
            self._draw_timed_mod_chips(footer)
        else:
            self._draw_lives_footer(footer)

        margin = self.px(RULE_BANNER_PINNED_MARGIN)
        self._rule_pinned_y = max(self.topbar_rect.bottom + self.px(8), self.score_capsule_rect.bottom + margin)

        # --- Bottom timer bar ---
        if self.scene is Scene.GAME:
            if self.mode is Mode.TIMED:
                tdur = float(self.settings.get("timed_duration", TIMED_DURATION))
                left = self.timer_timed.get()
                self.timebar.draw(left / max(0.001, tdur), f"{left:.1f}s")
            if self.mode is Mode.SPEEDUP and self.target_time > 0:
                remaining = self.timer_speed.get()
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

        if self.score > max(0, self.highscore):
            g = _pal("gold")
            return g["base"], g["hi"], g["soft"]

        if sel != "auto":
            p = _pal(sel)
            return p["base"], p["hi"], p["soft"]

        hs = max(1, int(self.highscore))      
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

        if self.mods_banner.is_active(now) or self.banner.is_active(now) or now < self.pause_until:
            self.rot_anim["pending"] = {
                "dur": float(max(0.15, dur)),
                "spins": float(spins),
                "swap_at": float(max(0.05, min(0.95, swap_at))),
            }
            return

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
        self.pause_until = max(self.pause_until, now + self.rot_anim["dur"])
        self.stop_timer()

    def _update_ring_rotation_anim(self) -> float:
        if not self.rot_anim["active"]:
            return 0.0
        now = self.now()
        t = (now - self.rot_anim["t0"]) / self.rot_anim["dur"]
        if t >= 1.0:
            self.ring_layout = dict(self.rot_anim["to_layout"])
            self._recompute_keymap()
            self.rot_anim["active"] = False
            self.rot_anim["swapped"] = True
            if self.level_cfg.memory_mode:
                self._memory_start_preview(reset_moves=True, force_unhide=True)
            return 0.0
        p = self._ease_out_cubic(max(0.0, min(1.0, t)))
        if (not self.rot_anim["swapped"]) and t >= self.rot_anim["swap_at"]:
            self.ring_layout = dict(self.rot_anim["to_layout"])
            self._recompute_keymap()
            self.rot_anim["swapped"] = True
        deg = 360.0 * self.rot_anim["spins"] * p
        return deg

    def _draw_spawn_animation(self, surface: pygame.Surface, name: str, rect: pygame.Rect) -> None:
        age = self.now() - self.symbol_spawn_time
        t = 0.0 if SYMBOL_ANIM_TIME <= 0 else min(1.0, max(0.0, age / SYMBOL_ANIM_TIME))
        eased = 1.0 - (1.0 - t) ** 3

        base_size = self.w * SYMBOL_BASE_SIZE_FACTOR
        scale = SYMBOL_ANIM_START_SCALE + (1.0 - SYMBOL_ANIM_START_SCALE) * eased
        scale *= self.fx.pulse_scale('symbol')
        size = int(base_size * scale)

        end_y = self.h * CENTER_Y_FACTOR
        start_y = end_y + self.h * SYMBOL_ANIM_OFFSET_Y
        cy = start_y + (end_y - start_y) * eased

        dx, dy = self.fx.shake_offset(self.w)

        draw_rect = pygame.Rect(0, 0, size, size)
        draw_rect.center = (int(self.w * 0.5 + dx), int(cy + dy))
        self.draw_symbol(surface, name, draw_rect)

        if hasattr(self.fx, "is_exit_active") and self.fx.is_exit_active() and self.exit_dir_pos:
            t = self.fx.exit_progress()
            eased2 = self._ease_out_cubic(t)

            dir_vec = {
                "RIGHT": (1, 0), "LEFT": (-1, 0), "TOP": (0, -1), "BOTTOM": (0, 1)
            }.get(self.exit_dir_pos, (0, 0))

            slide_dist = int(self.w * 0.35)  # distance to slide past the screen edge
            offx = int(dir_vec[0] * slide_dist * eased2)
            offy = int(dir_vec[1] * slide_dist * eased2)

            # fade out while sliding
            alpha = int(255 * (1.0 - eased2))

            symbol_layer = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            self.draw_symbol(symbol_layer, name, draw_rect.move(offx, offy))
            alpha_tint = pygame.Surface(symbol_layer.get_size(), pygame.SRCALPHA)
            alpha_tint.fill((255, 255, 255, alpha))
            symbol_layer.blit(alpha_tint, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            surface.blit(symbol_layer, (0, 0))
            return  # skip drawing the spawn transition twice

    def _draw_gameplay(self):
        self._blit_bg()
        self._draw_hud()

        base_size = int(self.w * SYMBOL_BASE_SIZE_FACTOR)
        base_rect = pygame.Rect(0, 0, base_size, base_size)
        base_rect.center = (int(self.w * 0.5), int(self.h * CENTER_Y_FACTOR))

        # --- Ring state ---
        spin_deg = self._update_ring_rotation_anim()
        self.ring.draw(base_rect.center, base_size, layout=self.ring_layout, spin_deg=spin_deg)

        if self.exit_dir_pos:
            if self.fx.is_exit_active() and self.fx.exit_symbol:
                # progress + easing
                t = self.fx.exit_progress()
                eased = t * t  # simple ease-in

                # direction vector toward the ring position
                cx, cy = base_rect.center
                r = int(base_rect.width * RING_RADIUS_FACTOR)
                target_xy = {
                    "TOP":    (cx, cy - r),
                    "RIGHT":  (cx + r, cy),
                    "LEFT":   (cx - r, cy),
                    "BOTTOM": (cx, cy + r),
                }[self.exit_dir_pos]

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
                pass
        else:
            if self.target:
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

        #  =================   MENU   =================

            elif self.scene is Scene.MENU:
                self._blit_bg()
                logo_path = str(PKG_DIR / "assets" / "images" / "logo2.png")
                logo_img = self.images.load(logo_path)

                # Vertical position
                ty = int(self.h * MENU_TITLE_Y_FACTOR)

                if logo_img:
                    iw, ih = logo_img.get_size()
                    max_w = int(self.w * 0.90)
                    max_h = int(self.h * 0.42)
                    s = min(max_w / max(1, iw), max_h / max(1, ih))
                    sw, sh = max(1, int(iw * s)), max(1, int(ih * s))
                    logo_s = pygame.transform.smoothscale(logo_img, (sw, sh))
                    tx = (self.w - sw) // 2
                    self.screen.blit(logo_s, (tx, ty))
                    title_bottom = ty + sh
                else:
                    title_bottom = ty

                # --- Mode badge beneath logo ---
                mode_label = "SPEED-UP" if self.mode is Mode.SPEEDUP else "TIMED"
                mode_text = f"Mode: {mode_label}"
                t_surf = self.mid.render(mode_text, True, MENU_MODE_TEXT_COLOR)
                pad_x = self.px(12); pad_y = self.px(8)
                bw = t_surf.get_width() + pad_x * 2
                bh = t_surf.get_height() + pad_y * 2
                bx = (self.w - bw) // 2
                gap = self.px(6)  # ~6 px UI
                by = title_bottom + gap
                badge_rect = pygame.Rect(bx, by, bw, bh)
                pygame.draw.rect(self.screen, MENU_MODE_BADGE_BG, badge_rect, border_radius=MENU_MODE_BADGE_RADIUS)
                pygame.draw.rect(self.screen, MENU_MODE_BADGE_BORDER, badge_rect, width=1, border_radius=MENU_MODE_BADGE_RADIUS)
                self.screen.blit(t_surf, (bx + pad_x, by + pad_y))

                # --- Footer hint ---
                hint = "ENTER = start    -    O = settings    -    ESC = quit"
                hf = self.font
                hw, hh = hf.size(hint)
                bottom_gap = self.px(24)
                self.draw_text(hint, pos=(self.w/2 - hw/2, self.h - bottom_gap - hh//4), font=hf, color=(210, 220, 235))

        #  =================   OVER   =================

            elif self.scene is Scene.OVER:
                self._blit_bg()
                cx, cy = self.w // 2, self.h // 2

                total_val = max(0, int(self.final_total))
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

                formula = f"{self.score} + {self.best_streak} streak"
                fw, fh = self.mid.size(formula)
                self.draw_text(
                    formula,
                    pos=(cx - fw // 2, cy + total_surf.get_height() // 2 + self.px(8)),
                    font=self.mid, color=ACCENT, shadow=True, glitch=False
                )

                if self.is_new_best:
                    badge = "NEW BEST!"
                    bx = cx - self.font.size(badge)[0] // 2
                    by = cy - total_surf.get_height() // 2 - self.px(18)
                    self.draw_chip(
                        badge, bx - self.px(12), by - self.px(6),
                        pad=self.px(8), radius=self.px(10),
                        bg=(22, 26, 34, 160), border=(120, 200, 255, 200),
                        text_color=INK, font=self.font
                    )

                info_text = "SPACE = play again   -   ESC = quit"
                iw, ih = self.font.size(info_text)
                self.draw_text(
                    info_text,
                    pos=(cx - iw // 2, self.h - ih - self.px(24)),
                    font=self.font, color=(210, 220, 235), shadow=True, glitch=False
                )

        #  =================   SETTINGS   =================

            elif self.scene is Scene.SETTINGS:
                self._blit_bg()

                # --- Title ---
                title_text = "Settings"
                tw, th = self.big.size(title_text)
                self.draw_text(title_text, pos=(self.w / 2 - tw / 2, self.h * SETTINGS_TITLE_Y_FACTOR), font=self.big)

                # --- View chips (BASIC / TIMED / SPEED-UP) ---
                label_basic = "BASIC"
                label_timed = "TIMED"
                label_spd   = "SPEED-UP"
                f = self.settings_font
                chip_gap = self.px(8)
                chips_y = int(self.h * SETTINGS_TITLE_Y_FACTOR) + self.big.get_height() + self.px(10)

                selected_on_switch = (not self.settings_focus_table and self.settings_idx == 0)

                def chip(txt, x, active, hover=False):
                    pad_x = self.px(12); pad_y = self.px(6)
                    cw, ch = f.size(txt)
                    w, h = cw + 2 * pad_x, ch + 2 * pad_y
                    scale = 1.06 if hover else 1.0
                    sw, sh = int(w * scale), int(h * scale)
                    draw_x = int(x - (sw - w) / 2)
                    draw_y = int(chips_y - (sh - h) / 2)
                    bg = (26, 30, 38, 240) if (active or hover) else (20, 22, 30, 160)
                    br = (140, 220, 255, 235) if (active or hover) else (80, 120, 160, 160)
                    r = pygame.Rect(draw_x, draw_y, sw, sh)
                    self._draw_round_rect(self.screen, r, bg, border=br, border_w=2, radius=self.px(12))
                    self.draw_text(txt, pos=(draw_x + (sw - cw)//2, draw_y + (sh - ch)//2),
                                font=f, color=ACCENT, shadow=True, glitch=False)
                    return sw

                labels = [label_basic, label_spd, label_timed]
                chip_widths = [f.size(t)[0] + self.px(24) for t in labels]
                total_w = sum(chip_widths) + chip_gap * 2
                start_x = self.w//2 - total_w//2

                x = start_x
                w_used = chip(label_basic, x, active=(self.settings_page == 0), hover=selected_on_switch and self.settings_page == 0); x += w_used + chip_gap
                w_used = chip(label_spd,   x, active=(self.settings_page == 1), hover=selected_on_switch and self.settings_page == 1); x += w_used + chip_gap
                _      = chip(label_timed, x, active=(self.settings_page == 2), hover=selected_on_switch and self.settings_page == 2)

                # --- Layout/viewport for the list below chips ---
                top_y = int(self.h * SETTINGS_LIST_Y_START_FACTOR)
                top_y += self.px(18)

                help1 = "UP/DOWN select  -  LEFT/RIGHT adjust"
                help2 = "ENTER save  -  ESC back"
                help_margin = self.px(SETTINGS_HELP_MARGIN_TOP)
                help_gap    = self.px(SETTINGS_HELP_GAP)
                w1h, h1 = self.font.size(help1)
                w2h, h2 = self.font.size(help2)
                help_block_h = help_margin + h1 + help_gap + h2 + self.px(12)

                viewport = pygame.Rect(0, top_y, self.w, max(50, self.h - top_y - help_block_h))
                prev_clip = self.screen.get_clip()
                self.screen.set_clip(viewport)

                items = self.settings_items()
                self._settings_row_tops = []
                item_spacing = self.px(SETTINGS_ITEM_SPACING)

                y_probe = top_y
                SECTION_TITLES = {0: "GENERAL", 1: "SPEED-UP", 2: "TIMED"}

                header_measured = False
                for (label, value, key) in items:
                    if key == "settings_page":
                        continue
                    if key is None:
                        if header_measured:
                            continue
                        raw = (label or "")
                        t = raw.strip("- ").strip().upper() or SECTION_TITLES[self.settings_page]
                        pad_x = self.px(12); pad_y = self.px(6)
                        tws, ths = self.settings_font.size(t)
                        row_h = ths + 2 * pad_y
                        self._settings_row_tops.append((y_probe, row_h))
                        y_probe += row_h + item_spacing
                        header_measured = True
                        continue

                    label_surf = self.settings_font.render(label, True, INK)
                    value_surf = self.settings_font.render(value, True, INK)
                    row_h = max(label_surf.get_height(), value_surf.get_height())
                    self._settings_row_tops.append((y_probe, row_h))
                    y_probe += row_h + item_spacing

                list_end_y = y_probe

                raw_table_h = self._levels_table_height()
                available_h = viewport.height
                scale_for_table = 1.0
                if self.settings_page == 1 and raw_table_h > available_h:
                    scale_for_table = max(0.55, available_h / raw_table_h)

                table_h = int(raw_table_h * scale_for_table)
                gap_list_table = self.px(8)

                content_h = (list_end_y - top_y)
                if self.settings_page == 1:
                    content_h += gap_list_table + table_h

                max_scroll = max(0, content_h - viewport.height)
                self.settings_scroll = max(0.0, min(float(max_scroll), float(self.settings_scroll)))

                y = top_y - int(self.settings_scroll)
                SECTION_TITLES = {0: "GENERAL", 1: "SPEED-UP", 2: "TIMED"}

                header_drawn = False
                for i, (label, value, key) in enumerate(items):
                    if key == "settings_page":
                        continue  # chips at the top already reflect the current view

                    if key is None:
                        if header_drawn:
                            continue
                        raw = (label or "")
                        t = raw.strip("- ").strip().upper() or SECTION_TITLES[self.settings_page]
                        pad_x = self.px(12); pad_y = self.px(6)
                        tws, ths = self.settings_font.size(t)
                        w = tws + 2 * pad_x
                        h = ths + 2 * pad_y
                        x = self.w // 2 - w // 2
                        rect = pygame.Rect(int(x), int(y), int(w), int(h))
                        self._draw_round_rect(self.screen, rect, (22, 26, 34, 220),
                                            border=(120, 200, 255, 230), border_w=2, radius=self.px(12))
                        self.draw_text(t, pos=(x + pad_x, y + pad_y),
                                    font=self.settings_font, color=ACCENT, shadow=True, glitch=False)
                        y += h + item_spacing
                        header_drawn = True
                        continue

                    selected = (i == self.settings_idx and not self.settings_focus_table)
                    value_to_draw = value
                    if selected and key == "highscore" and self.highscore != 0:
                        value_to_draw = "enter to reset"

                    row_h = self._draw_settings_row(label=label, value=value_to_draw, y=y, selected=selected)
                    y += row_h + item_spacing

                # --- Speed-up level table (advanced page only) ---
                if self.settings_page == 1 and self.mode is Mode.SPEEDUP:
                    table_top = y + gap_list_table
                    self._draw_levels_table(table_top, max_height=available_h, scale_override=scale_for_table)

                self.screen.set_clip(prev_clip)

                # --- Help at bottom ---
                base_y = self.h - (h1 + help_gap + h2) - self.px(14)
                self.draw_text(help1, pos=(self.w / 2 - w1h / 2, base_y), font=self.font)
                self.draw_text(help2, pos=(self.w / 2 - w2h / 2, base_y + h1 + help_gap), font=self.font)

        #  =================   INSTRUCTION   =================

            elif self.scene is Scene.INSTRUCTION:
                # show the tutorial overlay (ring + animations) first
                if self.tutorial:
                    self.tutorial.draw()

                title = self.instruction_text or f"LEVEL {self.level}"
                tw, th = self.big.size(title)
                title_y = int(self.h * 0.14)
                self.draw_text(title, pos=(self.w/2 - tw/2, title_y), font=self.big)

                if self.tutorial and getattr(self.tutorial, "caption", ""):
                    cap = self.tutorial.caption
                    cw, ch = self.mid.size(cap)
                    cap_margin = self.px(8)
                    self.draw_text(cap, pos=(self.w/2 - cw/2, title_y + th + cap_margin), font=self.mid, color=ACCENT)
                    self.tutorial.show_caption = False

                # --- Hint displayed in bottom-right corner ---
                hint = "ENTER/SPACE = start"
                fnt  = getattr(self, "hint_font", self.font)
                hw, hh = fnt.size(hint)
                pad = self.px(14)
                x = self.w - hw - pad
                y = self.h - hh - pad
                self.screen.blit(fnt.render(hint, True, (0, 0, 0)), (x + 2, y + 2))
                self.screen.blit(fnt.render(hint, True, (220, 200, 120)), (x, y))

                # --- Instruction screen fade-in ---
                t = (self.now() - getattr(self, "instruction_intro_t", 0.0)) / max(1e-6, getattr(self, "instruction_intro_dur", 0.0))
                t = max(0.0, min(1.0, t))
                alpha = int(255 * (1.0 - self._ease_out_cubic(t)))  # quick ease-out fade
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



__all__ = ['Game']





















