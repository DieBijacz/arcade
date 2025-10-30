from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Callable, Optional

import pygame

from .constants import *  # noqa: F401,F403

if TYPE_CHECKING:
    from .game import Game


class InputRing:
    def __init__(self, game: "Game") -> None:
        self.g = game

    def draw(
        self,
        center: tuple[int, int],
        base_size: int,
        *,
        layout: Optional[dict[str, str]] = None,
        spin_deg: float = 0.0,
    ) -> None:
        g = self.g
        cx, cy = center
        r = int(base_size * RING_RADIUS_FACTOR)

        base, hi, soft = g.ring_colors()

        t = g.now() - getattr(g, "_ring_anim_start", g.now())
        base_ccw = 60 + 8 * (g.level - 1)
        rot_ccw_deg = t * base_ccw

        margin = 36
        side = (r + margin) * 2
        C = side // 2
        out = pygame.Surface((side, side), pygame.SRCALPHA)

        def blit_to_out(surf: pygame.Surface) -> None:
            out.blit(surf, surf.get_rect(center=(C, C)))

        ring_path = g.cfg.get("images", {}).get("ring")
        ring_img = g.images.load(ring_path) if ring_path else None

        if ring_img:
            iw, ih = ring_img.get_size()
            scale = (r * 2) / max(iw, ih)
            ring_scaled = pygame.transform.smoothscale(ring_img, (int(iw * scale), int(ih * scale)))
            blit_to_out(ring_scaled)
        else:
            layers: list[pygame.Surface] = []

            def new_layer() -> pygame.Surface:
                surf = pygame.Surface((side, side), pygame.SRCALPHA)
                layers.append(surf)
                return surf

            l1 = new_layer()
            pygame.draw.circle(l1, (*base, 200), (C, C), r, width=6)
            pygame.draw.circle(l1, (*hi, 220), (C, C), int(r * RING_RING_INNER_SCALE), width=4)
            pygame.draw.circle(l1, (*soft, 150), (C, C), int(r * RING_RING_OUTER_SCALE), width=2)

            l2 = new_layer()
            pygame.draw.circle(l2, (*hi, 200), (C, C), int(r * RING_RING_INNER_SCALE * 0.9), width=2)
            pygame.draw.circle(l2, (*hi, 140), (C, C), int(r * RING_RING_OUTER_SCALE * 1.05), width=1)
            l2 = pygame.transform.rotozoom(l2, rot_ccw_deg * 0.75, 1.0)

            layers.append(l2)

            if g.level >= 3:
                l3 = new_layer()
                rect = pygame.Rect(0, 0, r * 2, r * 2)
                rect.center = (C, C)
                for w, a in ((12, 60), (20, 35)):
                    pygame.draw.arc(l3, (*hi, a), rect.inflate(w, w), 0, math.pi * 1.65, 8)
                layers.append(l3)

            if g.level >= 4:
                l4 = new_layer()
                orbit_r = int(r * 1.15)
                for k in range(3):
                    ang = t * 1.4 + k * (2 * math.pi / 3)
                    x = int(C + math.cos(ang) * orbit_r)
                    y = int(C + math.sin(ang) * orbit_r)
                    pygame.draw.circle(l4, (*base, 170), (x, y), 3)
                layers.append(l4)

            if g.level >= 5:
                l5 = new_layer()
                self._dashed_ring(l5, C, int(r * 1.20), dash_deg=16, gap_deg=10, width=3, alpha=150, color=base)
                l5 = pygame.transform.rotozoom(l5, rot_ccw_deg * 0.8, 1.0)
                layers.append(l5)

            for layer in layers:
                blit_to_out(layer)

        icons_visible = True
        if g.level_cfg.memory_mode and not g.memory_show_icons:
            icons_visible = bool(g.rot_anim.get("active", False))

        if icons_visible:
            icon_size = int(base_size * RING_ICON_SIZE_FACTOR)
            pos_xy = {"TOP": (cx, cy - r), "RIGHT": (cx + r, cy), "LEFT": (cx - r, cy), "BOTTOM": (cx, cy + r)}
            active_layout = layout if layout is not None else g.ring_layout
            for pos, (ix, iy) in pos_xy.items():
                name = active_layout.get(pos, DEFAULT_RING_LAYOUT[pos])
                scale = self.g.fx.ring_pulse_scale(pos)
                size = max(1, int(icon_size * scale))
                rect = pygame.Rect(0, 0, size, size)

                ox = C + (ix - cx)
                oy = C + (iy - cy)
                rect.center = (ox, oy)

                self.g.draw_symbol(out, name, rect)

        if abs(spin_deg) > 0.0001:
            out = pygame.transform.rotozoom(out, spin_deg, 1.0)

        self.g.screen.blit(out, out.get_rect(center=(cx, cy)))

    def _dashed_ring(
        self,
        surface: pygame.Surface,
        center: int,
        radius: int,
        *,
        dash_deg: float,
        gap_deg: float,
        width: int,
        alpha: int,
        color: tuple[int, int, int],
    ) -> None:
        total_deg = 360
        angle = 0.0
        rect = pygame.Rect(0, 0, radius * 2, radius * 2)
        rect.center = (center, center)
        while angle < total_deg:
            start = math.radians(angle)
            end = math.radians(min(total_deg, angle + dash_deg))
            pygame.draw.arc(surface, (*color, alpha), rect, start, end, width)
            angle += dash_deg + gap_deg


class TimeBar:
    def __init__(self, game: "Game") -> None:
        self.g = game

    def draw(self, ratio: float, label: Optional[str] = None) -> None:
        g = self.g
        ratio = max(0.0, min(1.0, ratio))
        if ratio <= TIMER_BAR_CRIT_TIME:
            fill_color = TIMER_BAR_CRIT_COLOR
        elif ratio <= TIMER_BAR_WARN_TIME:
            fill_color = TIMER_BAR_WARN_COLOR
        else:
            fill_color = TIMER_BAR_FILL

        pulse_scale = g.fx.pulse_scale("timer")
        bar_w = int(g.w * TIMER_BAR_WIDTH_FACTOR)
        base_h = int(TIMER_BAR_HEIGHT)
        bar_h = max(1, int(base_h * pulse_scale))
        bar_x = (g.w - bar_w) // 2
        bottom_margin = int(g.h * TIMER_BOTTOM_MARGIN_FACTOR)
        bar_y = g.h - bottom_margin - bar_h

        pygame.draw.rect(g.screen, TIMER_BAR_BG, (bar_x, bar_y, bar_w, bar_h), border_radius=TIMER_BAR_BORDER_RADIUS)

        fill_w = int(bar_w * ratio)
        if fill_w > 0:
            pygame.draw.rect(
                g.screen,
                fill_color,
                (bar_x, bar_y, fill_w, bar_h),
                border_radius=TIMER_BAR_BORDER_RADIUS,
            )

        pygame.draw.rect(
            g.screen,
            TIMER_BAR_BORDER,
            (bar_x, bar_y, bar_w, bar_h),
            width=TIMER_BAR_BORDER_W,
            border_radius=TIMER_BAR_BORDER_RADIUS,
        )

        indicator_x = max(bar_x, min(bar_x + bar_w, bar_x + fill_w))
        indicator_rect = pygame.Rect(
            indicator_x - TIMER_POSITION_INDICATOR_W // 2,
            bar_y - TIMER_POSITION_INDICATOR_PAD,
            TIMER_POSITION_INDICATOR_W,
            bar_h + TIMER_POSITION_INDICATOR_PAD * 2,
        )
        pygame.draw.rect(g.screen, ACCENT, indicator_rect)

        if label:
            timer_font = getattr(g, "timer_font", g.mid)
            surf = g.draw_text(label, color=TIMER_BAR_TEXT_COLOR, font=timer_font, shadow=True, glitch=False)
            tx = bar_x + (bar_w - surf.get_width()) // 2
            ty = bar_y - surf.get_height() - TIMER_LABEL_GAP
            g.screen.blit(surf, (tx, ty))


class PausableCountdown:
    def __init__(self, now_fn: Callable[[], float]) -> None:
        self._now = now_fn
        self.remaining = 0.0
        self.running = False
        self._t0 = 0.0

    def set(self, seconds: float) -> None:
        self.remaining = max(0.0, float(seconds))
        self.running = False
        self._t0 = 0.0

    def start(self, seconds: float) -> None:
        self.set(seconds)
        self.resume()

    def stop(self) -> None:
        if self.running:
            self.remaining = max(0.0, self.remaining - (self._now() - self._t0))
            self.running = False

    def resume(self) -> None:
        if not self.running and self.remaining > 0.0:
            self._t0 = self._now()
            self.running = True

    def get(self) -> float:
        if not self.running:
            return self.remaining
        return max(0.0, self.remaining - (self._now() - self._t0))

    def expired(self) -> bool:
        return self.get() <= 0.0

    def reset(self) -> None:
        self.remaining = 0.0
        self.running = False
        self._t0 = 0.0


__all__ = ["InputRing", "TimeBar", "PausableCountdown"]

