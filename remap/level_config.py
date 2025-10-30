from __future__ import annotations


from .config import CFG
from .constants import LEVEL_GOAL_PER_LEVEL
from .models import LEVELS, LevelCfg
from .mods import modifier_options, normalize_mods_raw


def apply_levels_from_cfg(cfg: dict | None = None) -> None:
    cfg = cfg or CFG
    lvl_cfg = cfg.get("levels", {}) or {}
    for key, value in lvl_cfg.items():
        try:
            lid = int(key)
            if lid in LEVELS and isinstance(value, dict):
                level = LEVELS[lid]
                if "hits" in value:
                    level.hits_required = int(max(1, min(999, value["hits"])))
                if "mods" in value and isinstance(value["mods"], list):
                    raw = [m if m in modifier_options() else "-" for m in value["mods"]]
                    level.modifiers = normalize_mods_raw(raw)
        except Exception:
            pass


def ensure_level_exists(lid: int) -> None:
    if lid in LEVELS:
        return
    LEVELS[lid] = LevelCfg(
        id=lid,
        rules=[],
        memory_mode=False,
        instruction=f"Level {lid}",
        hits_required=LEVEL_GOAL_PER_LEVEL,
        modifiers=["-", "-", "-"],
    )


__all__ = ["apply_levels_from_cfg", "ensure_level_exists"]






