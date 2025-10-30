from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List

from .constants import LEVEL_GOAL_PER_LEVEL, RULE_EVERY_HITS


class Mode(Enum):
    SPEEDUP = auto()
    TIMED = auto()


class Scene(Enum):
    MENU = auto()
    GAME = auto()
    OVER = auto()
    SETTINGS = auto()
    INSTRUCTION = auto()


class RuleType(Enum):
    MAPPING = auto()


@dataclass
class RuleSpec:
    type: RuleType
    banner_on_level_start: bool = False
    periodic_every_hits: int = 0


@dataclass
class LevelCfg:
    id: int
    rules: List[RuleSpec] = field(default_factory=list)
    memory_mode: bool = False
    memory_intro_sec: float = 3.0
    instruction: str = ""
    instruction_sec: float = 5.0
    hits_required: int = LEVEL_GOAL_PER_LEVEL
    control_flip_lr_ud: bool = False
    modifiers: List[str] = field(default_factory=list)


LEVELS: Dict[int, LevelCfg] = {
    1: LevelCfg(
        1,
        rules=[],
        instruction="Level 1 - Classic\nOdpowiadaj poprawnie.",
        hits_required=15,
    ),
    2: LevelCfg(
        2,
        rules=[
            RuleSpec(
                RuleType.MAPPING,
                banner_on_level_start=True,
                periodic_every_hits=RULE_EVERY_HITS,
            )
        ],
        instruction="Level 2 - New Rule\nZwracaj uwage na baner.",
        instruction_sec=5.0,
        hits_required=15,
    ),
    3: LevelCfg(
        3,
        rules=[],
        instruction="Level 3 - Rotacje\nUklad ringu zmienia sie w trakcie.",
        hits_required=15,
    ),
    4: LevelCfg(
        4,
        rules=[
            RuleSpec(
                RuleType.MAPPING,
                banner_on_level_start=True,
                periodic_every_hits=RULE_EVERY_HITS,
            )
        ],
        instruction="Level 4 - Mix\nReguly + rotacje.",
        instruction_sec=5.0,
        hits_required=15,
    ),
    5: LevelCfg(
        5,
        rules=[],
        memory_mode=True,
        memory_intro_sec=3.0,
        instruction="Level 5 - Memory\nZapamietaj uklad, potem ikony znikna.",
        hits_required=15,
    ),
    6: LevelCfg(
        6,
        rules=[],
        memory_mode=True,
        memory_intro_sec=3.0,
        instruction="Level 6 - Memory + Rotacje\nZapamietaj uklad - ring bedzie sie obracal.",
        instruction_sec=5.0,
        hits_required=15,
    ),
    7: LevelCfg(
        7,
        rules=[],
        memory_mode=False,
        control_flip_lr_ud=True,
        instruction="Level 7 - Odwrocone sterowanie\nLewo-Prawo oraz Gora-Dol sa zamienione.",
        instruction_sec=5.0,
        hits_required=15,
    ),
}


__all__ = ["Mode", "Scene", "RuleType", "RuleSpec", "LevelCfg", "LEVELS"]

