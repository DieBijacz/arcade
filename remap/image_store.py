from __future__ import annotations

import os
from typing import Optional

import pygame


class ImageStore:
    def __init__(self) -> None:
        self.cache: dict[str, pygame.Surface] = {}

    def load(self, path: str, *, allow_alpha: bool = True) -> Optional[pygame.Surface]:
        if not path:
            return None
        norm = os.path.normpath(path)
        if norm in self.cache:
            return self.cache[norm]
        try:
            img = pygame.image.load(norm)
            img = img.convert_alpha() if allow_alpha else img.convert()
            self.cache[norm] = img
            return img
        except Exception:
            return None


IMAGES = ImageStore()

__all__ = ["ImageStore", "IMAGES"]

