from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, TYPE_CHECKING

from .constants import RULE_EVERY_HITS
from .models import LevelCfg, Mode, RuleSpec, RuleType
from .symbols import SYMS

if TYPE_CHECKING:
    from .game import Game  # pragma: no cover


class BaseMod(ABC):
    id: str = ""
    timed_setting_key: Optional[str] = None

    def on_apply_level(self, game: "Game", level: LevelCfg) -> None:
        pass

    def apply_runtime_flags(self, game: "Game") -> None:
        pass

    def on_mods_applied(self, game: "Game") -> None:
        pass

    def on_level_start(self, game: "Game") -> None:
        pass

    def on_correct(self, game: "Game") -> None:
        pass

    def on_wrong(self, game: "Game") -> None:
        pass


class RemapMod(BaseMod):
    id = "remap"
    timed_setting_key = "timed_enable_remap"

    def on_apply_level(self, game: "Game", level: LevelCfg) -> None:
        every = int(game.settings.get("remap_every_hits", RULE_EVERY_HITS))
        level.rules.append(
            RuleSpec(RuleType.MAPPING, banner_on_level_start=True, periodic_every_hits=every)
        )

    def on_mods_applied(self, game: "Game") -> None:
        every = int(game.settings.get("timed_remap_every_hits", 6))
        game.rules.install(
            [RuleSpec(RuleType.MAPPING, banner_on_level_start=True, periodic_every_hits=every)]
        )
        if not game.rules.current_mapping:
            game.rules.roll_mapping(SYMS)

    def on_correct(self, game: "Game") -> None:
        if game.rules.on_correct():
            game.rules.roll_mapping(SYMS)
            game._start_mapping_banner(from_pinned=True)


class SpinMod(BaseMod):
    id = "spin"
    timed_setting_key = "timed_enable_spin"

    def on_level_start(self, game: "Game") -> None:
        game.start_ring_rotation(dur=0.8, spins=2.0, swap_at=0.5)

    def on_mods_applied(self, game: "Game") -> None:
        game.start_ring_rotation(dur=0.8, spins=2.0, swap_at=0.5)

    def on_correct(self, game: "Game") -> None:
        if game.mode is Mode.SPEEDUP:
            every = int(game.settings.get("spin_every_hits", 0))
            if every > 0 and (game.hits_in_level % every == 0):
                game.start_ring_rotation(dur=0.8, spins=2.0, swap_at=0.5)
        else:
            every = int(game.settings.get("timed_spin_every_hits", 0))
            if every > 0 and (game.hits_in_level % every == 0):
                game.start_ring_rotation(dur=0.8, spins=2.0, swap_at=0.5)


class MemoryMod(BaseMod):
    id = "memory"
    timed_setting_key = "timed_enable_memory"

    def on_apply_level(self, game: "Game", level: LevelCfg) -> None:
        level.memory_mode = True

    def on_level_start(self, game: "Game") -> None:
        if game.level_cfg.memory_mode:
            game._memory_start_preview(reset_moves=False, force_unhide=True)

    def on_mods_applied(self, game: "Game") -> None:
        game.level_cfg.memory_mode = True
        game._memory_start_preview(reset_moves=False, force_unhide=True)


class JoystickMod(BaseMod):
    id = "joystick"
    timed_setting_key = "timed_enable_joystick"

    def on_apply_level(self, game: "Game", level: LevelCfg) -> None:
        level.control_flip_lr_ud = True

    def apply_runtime_flags(self, game: "Game") -> None:
        game.level_cfg.control_flip_lr_ud = True
        game._recompute_keymap()


class _ModRegistry:
    def __init__(self) -> None:
        self._mods: Dict[str, BaseMod] = {}

    def register(self, mod: BaseMod) -> None:
        self._mods[mod.id] = mod

    def get(self, mod_id: str) -> Optional[BaseMod]:
        return self._mods.get(mod_id)

    def ids(self) -> List[str]:
        return list(self._mods.keys())

    def items(self) -> List[tuple[str, BaseMod]]:
        return list(self._mods.items())


MODS = _ModRegistry()
MODS.register(RemapMod())
MODS.register(SpinMod())
MODS.register(MemoryMod())
MODS.register(JoystickMod())


def modifier_options() -> List[str]:
    return ["-"] + MODS.ids() + ["random"]

def mods_from_ids(ids: List[str]) -> List[BaseMod]:
    out: List[BaseMod] = []
    for mod_id in ids or []:
        mod = MODS.get(mod_id)
        if mod:
            out.append(mod)
    return out


def allowed_mod_ids_from_settings(settings: dict) -> List[str]:
    out = []
    for mod_id, mod in MODS.items():
        key = getattr(mod, "timed_setting_key", None)
        if not key or bool(settings.get(key, True)):
            out.append(mod_id)
    return out


def normalize_mods_raw(mods: List[str]) -> List[str]:
    valid = set(modifier_options())
    fixed = set(MODS.ids())
    out: List[str] = []
    seen_fixed: set[str] = set()
    for mod in (mods or [])[:3]:
        mod = mod if mod in valid else "-"
        if mod in fixed:
            if mod in seen_fixed:
                out.append("-")
            else:
                seen_fixed.add(mod)
                out.append(mod)
        else:
            out.append(mod)
    while len(out) < 3:
        out.append("-")
    return out[:3]

__all__ = [
    "BaseMod",
    "RemapMod",
    "SpinMod",
    "MemoryMod",
    "JoystickMod",
    "MODS",
    "modifier_options",
    "mods_from_ids",
    "allowed_mod_ids_from_settings",
    "normalize_mods_raw",
]









