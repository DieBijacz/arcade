from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pygame

from .models import Mode


@dataclass
class ModeProfile:
    key: Mode
    label: str
    order: int
    menu_bg_path: str
    game_bg_path: Optional[str] = None
    menu_music_path: Optional[str] = None
    game_music_path: Optional[str] = None
    crossfade_ms: int = 600

    _bg_cache_key: Optional[tuple[int, int]] = field(default=None, init=False)
    _bg_scaled: Optional[pygame.Surface] = field(default=None, init=False)


class ModeRegistry:
    def __init__(self, profiles: List[ModeProfile], *, initial_key: Mode) -> None:
        self.modes = sorted(list(profiles), key=lambda profile: profile.order)
        try:
            self.idx = next(i for i, mode in enumerate(self.modes) if mode.key == initial_key)
        except StopIteration:
            self.idx = 0

    def current(self) -> ModeProfile:
        return self.modes[self.idx]

    def next_index(self, delta: int) -> Optional[int]:
        target = self.idx + (1 if delta > 0 else -1)
        if 0 <= target < len(self.modes):
            return target
        return None

    def set_index(self, index: int) -> None:
        if 0 <= index < len(self.modes):
            self.idx = index


__all__ = ["ModeProfile", "ModeRegistry"]

