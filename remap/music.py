from __future__ import annotations

import os
from typing import Optional

import pygame


class MusicController:
    def __init__(self, *, volume: float = 0.6) -> None:
        self.current_path: Optional[str] = None
        self.volume = max(0.0, min(1.0, float(volume)))
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
        except Exception:
            pass

    def set_volume(self, value: float) -> None:
        self.volume = max(0.0, min(1.0, float(value)))
        try:
            if pygame.mixer.get_init():
                pygame.mixer.music.set_volume(self.volume)
        except Exception:
            pass

    def fade_to(self, path: Optional[str], *, ms: int = 600, loop: int = -1) -> None:
        if not path or not os.path.exists(path):
            return
        try:
            if pygame.mixer.get_init():
                try:
                    pygame.mixer.music.fadeout(max(0, int(ms)))
                except Exception:
                    pass
                pygame.mixer.music.load(path)
                pygame.mixer.music.set_volume(self.volume)
                pygame.mixer.music.play(loop, fade_ms=max(0, int(ms)))
                self.current_path = path
        except Exception:
            pass


__all__ = ["MusicController"]

