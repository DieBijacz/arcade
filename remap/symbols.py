from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import pygame

from .constants import (
    SYMBOL_COLORS,
    SYMBOL_CIRCLE_RADIUS_FACTOR,
    SYMBOL_CROSS_K_FACTOR,
    SYMBOL_DRAW_THICKNESS,
    SYMBOL_SQUARE_RADIUS,
    SYMBOL_TRIANGLE_POINT_FACTOR,
)
from .image_store import ImageStore


@dataclass(frozen=True)
class Symbol:
    name: str
    color: tuple[int, int, int]
    image_cfg_key: str

    def draw(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        *,
        images: ImageStore,
        cfg: dict,
    ) -> None:
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
    "CIRCLE": Symbol("CIRCLE", SYMBOL_COLORS["CIRCLE"], "symbol_circle"),
    "SQUARE": Symbol("SQUARE", SYMBOL_COLORS["SQUARE"], "symbol_square"),
    "CROSS": Symbol("CROSS", SYMBOL_COLORS["CROSS"], "symbol_cross"),
}

SYMS: List[str] = list(SYMBOLS.keys())

__all__ = ["Symbol", "SYMBOLS", "SYMS"]

