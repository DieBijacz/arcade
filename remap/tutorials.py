from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Tuple

import pygame

from .constants import *  # noqa: F401,F403
from .symbols import SYMS

if TYPE_CHECKING:
    from .game import Game


@dataclass
class DemoItem:
    at: float
    symbol: str
    slide_delay: float = 1.0
    slide_duration: float = 0.55
    use_mapping: bool = False
    rotate_ring: bool = False
    tail_sec: float = 0.20


class TutorialPlayer:
    def __init__(
        self,
        game: "Game",
        items: List[DemoItem],
        *,
        caption: str = "",
        mapping_pair: Optional[Tuple[str, str]] = None,
        show_mapping_banner: bool = False,
        sequential: bool = True,
        seq_gap: float = 0.12,
        static_banner: bool = True,
    ) -> None:
        self.g = game
        self.caption = caption
        self.show_caption = True

        self.t0 = game.now()
        self.ring_layout: dict[str, str] = dict(game.ring_layout)
        self.items = sorted(items, key=lambda item: item.at)
        self._spawned_idx = -1
        self._active: List[dict] = []
        self._finished = False

        self.mapping_pair = mapping_pair
        self.show_mapping_banner = bool(show_mapping_banner)
        self.static_banner = bool(static_banner)
        self.banner_start_t = self.g.now() if show_mapping_banner and mapping_pair else None

        self.sequential = bool(sequential)
        self.seq_gap = float(seq_gap)
        self._next_ready_at = self.t0

    def _pos_for_symbol(self, sym: str) -> str:
        return next(pos for pos, symbol in self.ring_layout.items() if symbol == sym)

    def _target_for(self, sym: str, use_mapping: bool) -> str:
        if use_mapping and self.mapping_pair and sym == self.mapping_pair[0]:
            return self._pos_for_symbol(self.mapping_pair[1])
        return self._pos_for_symbol(sym)

    def update(self) -> None:
        now = self.g.now()
        t = now - self.t0

        still: List[dict] = []
        for inst in self._active:
            item: DemoItem = inst["item"]
            started = inst["started"]
            slide_start = inst["slide_start"]

            if slide_start is None and (now - started) >= max(0.0, item.slide_delay):
                inst["slide_start"] = now
                slide_start = now

            tail = item.tail_sec
            if slide_start is None:
                lifetime = now - started
            else:
                lifetime = now - slide_start

            if lifetime <= item.slide_duration + tail:
                still.append(inst)

        before = bool(self._active)
        self._active = still

        if self.sequential:
            if not before and self._spawned_idx + 1 < len(self.items):
                self._next_ready_at = now + self.seq_gap
            while (self._spawned_idx + 1) < len(self.items):
                nxt = self.items[self._spawned_idx + 1]
                if t >= max(nxt.at, 0.0) and now >= self._next_ready_at:
                    self._spawned_idx += 1
                    inst = {"item": nxt, "started": now, "slide_start": None}
                    self._active.append(inst)
                else:
                    break
        else:
            while (self._spawned_idx + 1) < len(self.items) and self.items[self._spawned_idx + 1].at <= t:
                self._spawned_idx += 1
                inst = {"item": self.items[self._spawned_idx], "started": now, "slide_start": None}
                self._active.append(inst)

        if (self._spawned_idx + 1) >= len(self.items) and not self._active:
            self._finished = True

    def is_finished(self) -> bool:
        return bool(self._finished)

    def _draw_mapping_banner(self) -> None:
        if not (self.mapping_pair and self.show_mapping_banner and self.banner_start_t is not None):
            return

        g = self.g

        if self.static_banner:
            base_size = int(g.w * SYMBOL_BASE_SIZE_FACTOR)
            cx, cy = int(g.w * 0.5), int(g.h * CENTER_Y_FACTOR)
            r = int(base_size * RING_RADIUS_FACTOR)

            panel_scale = RULE_BANNER_PIN_SCALE * g.fx.pulse_scale("banner")
            symbol_scale = RULE_SYMBOL_SCALE_PINNED
            panel, shadow = g._render_rule_panel_surface(
                self.mapping_pair, panel_scale, symbol_scale, label_font=g.rule_font_pinned
            )
            pw, ph = panel.get_size()

            px = (g.w - pw) // 2
            margin = g.px(12)
            lift = int(g.h * 0.06)
            safe_top = int(g.h * 0.18)

            py = cy - r - ph - margin - lift
            py = max(safe_top, py)

            g.screen.blit(shadow, (px + 3, py + 5))
            g.screen.blit(panel, (px, py))
            return

        now = g.now()
        elapsed = now - self.banner_start_t
        IN, HOLD, OUT = RULE_BANNER_IN_SEC, RULE_BANNER_HOLD_SEC, RULE_BANNER_TO_TOP_SEC
        total = IN + HOLD + OUT
        if elapsed > total:
            panel, shadow = g._render_rule_panel_surface(
                self.mapping_pair,
                RULE_BANNER_PIN_SCALE,
                RULE_SYMBOL_SCALE_PINNED,
                label_font=g.rule_font_pinned,
            )
            pw, ph = panel.get_size()
            px = (g.w - pw) // 2
            py = int(getattr(g, "_rule_pinned_y", g.topbar_rect.bottom + g.px(12)))
            g.screen.blit(shadow, (px + 3, py + 5))
            g.screen.blit(panel, (px, py))
            return

        if elapsed <= IN:
            p = g._ease_out_cubic(elapsed / max(1e-6, IN))
            panel_scale = RULE_BANNER_PIN_SCALE + (1.0 - RULE_BANNER_PIN_SCALE) * p
            symbol_scale = RULE_SYMBOL_SCALE_PINNED + (RULE_SYMBOL_SCALE_CENTER - RULE_SYMBOL_SCALE_PINNED) * p
            start_y = -int(g.h * 0.35)
            mid_y = int(g.h * 0.30)
            y = int(start_y + (mid_y - start_y) * p)
            font = g.rule_font_center
        elif elapsed <= IN + HOLD:
            panel_scale = 1.0
            symbol_scale = RULE_SYMBOL_SCALE_CENTER
            y = int(g.h * 0.30)
            font = g.rule_font_center
        else:
            p = g._ease_out_cubic((elapsed - IN - HOLD) / max(1e-6, OUT))
            panel_scale = 1.0 + (RULE_BANNER_PIN_SCALE - 1.0) * p
            symbol_scale = RULE_SYMBOL_SCALE_CENTER + (RULE_SYMBOL_SCALE_PINNED - RULE_SYMBOL_SCALE_CENTER) * p
            mid_y = int(g.h * 0.30)
            pinned_y = int(getattr(g, "_rule_pinned_y", g.topbar_rect.bottom + g.px(12)))
            y = int(mid_y + (pinned_y - mid_y) * p)
            font = g.rule_font_pinned

        panel, shadow = g._render_rule_panel_surface(self.mapping_pair, panel_scale, symbol_scale, label_font=font)
        pw, ph = panel.get_size()
        px = (g.w - pw) // 2
        g.screen.blit(shadow, (px + 3, y + 5))
        g.screen.blit(panel, (px, y))

    def draw(self) -> None:
        g = self.g
        now = g.now()
        self.update()

        g._blit_bg()
        base_size = int(g.w * SYMBOL_BASE_SIZE_FACTOR)
        cx, cy = int(g.w * 0.5), int(g.h * CENTER_Y_FACTOR)
        g.ring.draw((cx, cy), base_size, layout=self.ring_layout, spin_deg=0.0)

        try:
            self._draw_mapping_banner()
        except Exception:
            pass

        for inst in self._active:
            item: DemoItem = inst["item"]
            started: float = inst["started"]
            slide_start = inst.get("slide_start")
            start_x, start_y = cx, cy
            target_pos = self._target_for(item.symbol, item.use_mapping)
            ring_radius = int(base_size * RING_RADIUS_FACTOR)
            pos_xy = {
                "TOP": (cx, cy - ring_radius),
                "RIGHT": (cx + ring_radius, cy),
                "LEFT": (cx - ring_radius, cy),
                "BOTTOM": (cx, cy + ring_radius),
            }
            end_x, end_y = pos_xy.get(target_pos, (cx, cy))

            if slide_start is None or item.slide_duration <= 0.0:
                progress = 0.0
            else:
                t = max(0.0, min(1.0, (now - slide_start) / max(1e-6, item.slide_duration)))
                progress = g._ease_out_cubic(t)

            x = int(start_x + (end_x - start_x) * progress)
            y = int(start_y + (end_y - start_y) * progress)
            scale = 1.0 - 0.12 * progress

            size = max(1, int(g.w * SYMBOL_BASE_SIZE_FACTOR * scale))
            rect = pygame.Rect(0, 0, size, size)
            rect.center = (x, y)
            g.draw_symbol(g.screen, item.symbol, rect)

    def rewind_to_start(self) -> None:
        self._active.clear()
        self._spawned_idx = -1
        self._finished = False
        self.banner_start_t = self.g.now()
        self.t0 = self.g.now()


def build_tutorial_from_state(
    game: "Game",
    *,
    mods: List[str],
    mapping: Optional[Tuple[str, str]] = None,
    intent: str = "full",
) -> Optional[TutorialPlayer]:
    active = list(mods or [])

    has_remap = "remap" in active
    has_rotate = "spin" in active
    has_memory = "memory" in active or bool(getattr(game.level_cfg, "memory_mode", False))
    has_invert = "joystick" in active or bool(getattr(game.level_cfg, "control_flip_lr_ud", False))

    parts = []
    if has_remap:
        parts.append("Remap")
    if has_rotate:
        parts.append("Rotate")
    if has_memory:
        parts.append("Memory")
    if has_invert:
        parts.append("Controls flipped")
    caption = " + ".join(parts) if parts else "Classic"

    def sym(exclude: set[str] | None = None) -> str:
        exclude = exclude or set()
        choices = [s for s in SYMS if s not in exclude]
        return random.choice(choices) if choices else random.choice(SYMS)

    items: List[DemoItem] = []
    mapping_pair: Optional[Tuple[str, str]] = None

    if has_remap:
        if mapping:
            a, b = mapping
        else:
            a = sym()
            b = sym({a})
        mapping_pair = (a, b)
        neutral = sym({a, b})
        items += [
            DemoItem(at=0.0, symbol=a, slide_delay=1.0, slide_duration=0.60, use_mapping=True, rotate_ring=False),
            DemoItem(at=0.0, symbol=neutral, slide_delay=1.0, slide_duration=0.60, use_mapping=False, rotate_ring=False),
            DemoItem(at=0.0, symbol=a, slide_delay=1.0, slide_duration=0.60, use_mapping=True, rotate_ring=False),
        ]
    else:
        x = sym()
        y = sym({x})
        z = sym({x, y})
        items += [
            DemoItem(at=0.0, symbol=x, slide_delay=1.0, slide_duration=0.60),
            DemoItem(at=0.0, symbol=y, slide_delay=1.0, slide_duration=0.60),
            DemoItem(at=0.0, symbol=z, slide_delay=1.0, slide_duration=0.60),
        ]

    if has_rotate and len(items) >= 2:
        items[0].rotate_ring = True
        items[1].rotate_ring = True

    return TutorialPlayer(
        game,
        items,
        caption=caption,
        mapping_pair=mapping_pair,
        show_mapping_banner=bool(mapping_pair),
        static_banner=True,
        sequential=True,
        seq_gap=0.12,
    )


def build_tutorial_for_speed(game: "Game") -> Optional[TutorialPlayer]:
    level_cfg = game.level_cfg
    resolved = list(getattr(level_cfg, "_mods_resolved", level_cfg.modifiers or []))
    return build_tutorial_from_state(game, mods=resolved, mapping=None, intent="full")


def build_tutorial_for_timed(game: "Game", *, mods: Optional[List[str]] = None) -> Optional[TutorialPlayer]:
    active = list(mods if mods is not None else game.timed_active_mods)
    return build_tutorial_from_state(game, mods=active, mapping=game.rules.current_mapping, intent="full")


__all__ = [
    "DemoItem",
    "TutorialPlayer",
    "build_tutorial_from_state",
    "build_tutorial_for_speed",
    "build_tutorial_for_timed",
]

