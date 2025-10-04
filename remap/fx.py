from __future__ import annotations
from typing import Optional, Dict, Tuple
import random as _rand
import pygame

# === Stałe efektów (trzymamy je tutaj, by nie zależeć od main.py) ===

# Glitch ekranu
GLITCH_DURATION = 0.20             # s
GLITCH_PIXEL_FACTOR_MAX = 0.10     # 0..1 jak mocne “downsample”

# Glitch tekstu
TEXT_GLITCH_DURATION = 0.5
TEXT_GLITCH_MIN_GAP = 1.0
TEXT_GLITCH_MAX_GAP = 5.0

# Shake
SHAKE_DURATION = 0.12
SHAKE_AMPLITUDE_FACT = 0.012
SHAKE_FREQ_HZ = 18.0

# Pulse
PULSE_BASE_DURATION = 0.30
PULSE_BASE_MAX_SCALE = 1.18
PULSE_KIND_SCALE = {
    "symbol": 1.00,
    "streak": 1.06,
    "banner": 1.04,
    "score":  1.10,
    "timer":  1.10,
}
PULSE_KIND_DURATION = {
    "symbol": 0.30,
    "streak": 0.30,
    "banner": 0.30,
    "score":  0.26,
    "timer":  0.40,
}

# Exit-slide (czas trwania animacji “wyjazdu” symbolu)
EXIT_SLIDE_SEC = 0.12

# Tryb glitch
from .enums import GlitchMode


class EffectsManager:
    def __init__(self, now_fn, *, glitch_mode: GlitchMode = GlitchMode.BOTH):
        self.now = now_fn

        # easing
        self.easing_default = "in_out"
        self._easing_map: Dict[str, callable] = {}
        self._init_easing_map()
        self._timings = {
            "menu_slide_sec": 0.30,
        }

        # flags wynikające z trybu
        self.screen_glitch = glitch_mode in (GlitchMode.SCREEN, GlitchMode.BOTH)
        self.text_glitch   = glitch_mode in (GlitchMode.TEXT,   GlitchMode.BOTH)

        # shake
        self.shake_start = 0.0
        self.shake_until = 0.0

        # glitch (post)
        self.glitch_active_until = 0.0
        self.glitch_start_time = 0.0
        self.glitch_mag = 1.0

        # text glitch
        self.text_glitch_active_until = 0.0
        self.next_text_glitch_at = self.now() + _rand.uniform(TEXT_GLITCH_MIN_GAP, TEXT_GLITCH_MAX_GAP)

        # pulses
        self._pulses: Dict[str, Tuple[float, float]] = {
            'symbol': (0.0, 0.0),
            'streak': (0.0, 0.0),
            'banner': (0.0, 0.0),
            'score':  (0.0, 0.0),
            'timer':  (0.0, 0.0),
        }
        self._ring_pulses: Dict[str, Tuple[float, float]] = {}

        # exit slide
        self.exit_active = False
        self.exit_start = 0.0
        self.exit_symbol: Optional[str] = None
        self.exit_duration = EXIT_SLIDE_SEC

    # ---------- easing ----------
    def _init_easing_map(self) -> None:
        self._easing_map = {
            "linear":    self._ease_linear,
            "in_out":    self._ease_in_out,
            "out_cubic": self._ease_out_cubic,
            "in_cubic":  self._ease_in_cubic,
        }

    @staticmethod
    def _clamp01(t: float) -> float:
        return 0.0 if t <= 0.0 else 1.0 if t >= 1.0 else t

    def _ease_linear(self, t: float) -> float:
        return self._clamp01(t)

    def _ease_in_out(self, t: float) -> float:
        t = self._clamp01(t)
        return t * t * (3.0 - 2.0 * t)

    def _ease_out_cubic(self, t: float) -> float:
        t = self._clamp01(t)
        return 1.0 - (1.0 - t) ** 3

    def _ease_in_cubic(self, t: float) -> float:
        t = self._clamp01(t)
        return t ** 3

    def ease(self, name: str, t: float) -> float:
        fn = self._easing_map.get(name, self._ease_linear)
        return fn(t)

    def e(self, t: float, name: str | None = None) -> float:
        return self.ease(name or self.easing_default, t)

    def set_default_ease(self, name: str) -> None:
        if name in self._easing_map:
            self.easing_default = name

    def set_timing(self, key: str, seconds: float) -> None:
        try:
            self._timings[key] = float(seconds)
        except Exception:
            pass

    def get_timing(self, key: str, default: float = 0.0) -> float:
        return float(self._timings.get(key, default))

    @property
    def menu_slide_sec(self) -> float:
        return self.get_timing("menu_slide_sec", 0.30)

    # ---------- tryb glitch ----------
    def set_glitch_mode(self, mode: GlitchMode):
        self.screen_glitch = mode in (GlitchMode.SCREEN, GlitchMode.BOTH)
        self.text_glitch   = mode in (GlitchMode.TEXT,   GlitchMode.BOTH)
        if not self.screen_glitch:
            self.clear_transients()

    def clear_transients(self):
        self.shake_start = self.shake_until = 0.0
        self.glitch_active_until = self.glitch_start_time = 0.0
        self.glitch_mag = 1.0
        self.text_glitch_active_until = 0.0
        self._pulses = {k: (0.0, 0.0) for k in self._pulses}
        self._ring_pulses.clear()

    # ---------- triggers ----------
    def trigger_shake(self, duration: float = SHAKE_DURATION):
        now = self.now()
        self.shake_start = now
        self.shake_until = now + max(0.01, duration)

    def trigger_glitch(self, *, mag: float = 1.0, duration: float = GLITCH_DURATION):
        if not self.screen_glitch:
            return
        now = self.now()
        self.glitch_mag = max(0.0, mag)
        self.glitch_active_until = now + max(0.01, duration)
        self.glitch_start_time = now
        self.trigger_shake()
        if _rand.random() < 0.5:
            self.trigger_text_glitch()

    def trigger_text_glitch(self, duration: float = TEXT_GLITCH_DURATION):
        if not self.text_glitch:
            return
        now = self.now()
        self.text_glitch_active_until = now + max(0.05, duration)
        self.next_text_glitch_at = now + _rand.uniform(TEXT_GLITCH_MIN_GAP, TEXT_GLITCH_MAX_GAP)

    def maybe_schedule_text_glitch(self):
        if not self.text_glitch:
            return
        now = self.now()
        if now >= self.next_text_glitch_at and not self.is_text_glitch_active():
            self.trigger_text_glitch()

    def is_text_glitch_active(self) -> bool:
        return self.text_glitch and (self.now() < self.text_glitch_active_until)

    def trigger_pulse(self, kind: str, duration: float | None = None):
        if kind not in self._pulses:
            return
        dur = float(duration if duration is not None else PULSE_KIND_DURATION.get(kind, PULSE_BASE_DURATION))
        now = self.now()
        self._pulses[kind] = (now, now + max(1e-3, dur))

    def trigger_pulse_symbol(self): self.trigger_pulse('symbol')
    def trigger_pulse_streak(self): self.trigger_pulse('streak')
    def trigger_pulse_banner(self): self.trigger_pulse('banner')
    def trigger_pulse_score(self):  self.trigger_pulse('score')

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
        import math
        # delikatny “pop”
        local_max = 1.14
        return 1.0 + (local_max - 1.0) * math.sin(math.pi * max(0.0, min(1.0, t)))

    # ---------- queries / math ----------
    def _pulse_curve01(self, t: float, kind: str) -> float:
        import math
        t = max(0.0, min(1.0, t))
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

    # ---------- shake offset ----------
    def shake_offset(self, screen_w: int) -> tuple[float, float]:
        import math
        now = self.now()
        if now >= self.shake_until:
            return (0.0, 0.0)
        sh_t = max(0.0, min(1.0, (now - self.shake_start) / SHAKE_DURATION))
        env = 1.0 - sh_t
        amp = screen_w * SHAKE_AMPLITUDE_FACT * env
        phase = 2.0 * math.pi * SHAKE_FREQ_HZ * (now - self.shake_start)
        dx = amp * math.sin(phase)
        dy = 0.5 * amp * math.cos(phase * 0.9)
        return (dx, dy)

    # ---------- post-process glitch ----------
    def apply_postprocess(self, frame: pygame.Surface, w: int, h: int) -> pygame.Surface:
        if not self.screen_glitch:
            return frame
        now = self.now()
        if now >= self.glitch_active_until:
            return frame

        # jak “wzburzony” glitch w czasie (dzwon)
        dur = max(1e-6, GLITCH_DURATION)
        t = 1.0 - (self.glitch_active_until - now) / dur
        vigor = (1 - abs(0.5 - t) * 2)
        strength = max(0.0, min(1.0, vigor * self.glitch_mag))

        out = frame

        # 1) Pixelation
        pf = GLITCH_PIXEL_FACTOR_MAX * strength
        if pf > 0:
            sw, sh = max(1, int(w * (1 - pf))), max(1, int(h * (1 - pf)))
            small = pygame.transform.smoothscale(frame, (sw, sh))
            out = pygame.transform.scale(small, (w, h))

        # 2) RGB split
        ch_off = int(6 * strength) + _rand.randint(0, 2)
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

        # 3) Displaced horizontal bands
        if _rand.random() < 0.9:
            bands = _rand.randint(2, 4)
            band_h = max(4, h // (bands * 8))
            for _ in range(bands):
                y = _rand.randint(0, h - band_h)
                dx = _rand.randint(-int(w * 0.03 * strength), int(w * 0.03 * strength))
                slice_rect = pygame.Rect(0, y, w, band_h)
                slice_surf = out.subsurface(slice_rect).copy()
                out.blit(slice_surf, (dx, y))

        # 4) Colored blocks (losowe “artefakty”)
        if _rand.random() < 0.4 * strength:
            bw = _rand.randint(w // 12, w // 4)
            bh = _rand.randint(h // 24, h // 8)
            x = _rand.randint(0, max(0, w - bw))
            y = _rand.randint(0, max(0, h - bh))
            col = (
                _rand.randint(180, 255),
                _rand.randint(120, 255),
                _rand.randint(120, 255),
                _rand.randint(40, 100),
            )
            pygame.draw.rect(out, col, (x, y, bw, bh))

        return out

    # ---------- exit slide ----------
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
