from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

from .models import RuleSpec, RuleType


class RuleManager:
    def __init__(self) -> None:
        self.active: Dict[RuleType, RuleSpec] = {}
        self.current_mapping: Optional[Tuple[str, str]] = None
        self.mapping_every_hits = 0
        self.hits_since_roll = 0

    def install(self, specs: List[RuleSpec]) -> None:
        self.active.clear()
        self.current_mapping = None
        self.mapping_every_hits = 0
        self.hits_since_roll = 0
        for spec in specs or []:
            self.active[spec.type] = spec
            if spec.type is RuleType.MAPPING:
                self.mapping_every_hits = int(spec.periodic_every_hits or 0)

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
        b_choices = [s for s in syms if s != a]
        if self.current_mapping and self.current_mapping[0] == a:
            b_choices = [s for s in b_choices if s != self.current_mapping[1]] or b_choices
        b = random.choice(b_choices)
        self.current_mapping = (a, b)
        return self.current_mapping

    def apply(self, stimulus: str) -> str:
        if self.current_mapping and stimulus == self.current_mapping[0]:
            return self.current_mapping[1]
        return stimulus


class BannerManager:
    def __init__(self, in_sec: float, hold_sec: float, out_sec: float) -> None:
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
        t = max(0.0, min(self.total, now - self.anim_start))
        if t <= self.in_sec:
            return "in", (t / max(1e-6, self.in_sec))
        if t <= self.in_sec + self.hold_sec:
            return "hold", 1.0
        return "out", ((t - self.in_sec - self.hold_sec) / max(1e-6, self.out_sec))


__all__ = ["RuleManager", "BannerManager"]

