from __future__ import annotations

from .config import CFG
from .constants import (
    ADDITIONAL_RULE_TIME,
    FPS,
    LEVELS_ACTIVE_FOR_NOW,
    MEMORY_HIDE_AFTER_SEC,
    RULE_EVERY_HITS,
    TIMED_DURATION,
)


def settings_defaults_from_cfg() -> list[tuple[str, object]]:
    disp = CFG.get("display", {}) or {}
    timed = CFG.get("timed", {}) or {}
    audio = CFG.get("audio", {}) or {}
    rules = CFG.get("rules", {}) or {}
    effects = CFG.get("effects", {}) or {}

    return [
        # ===== BASIC / DISPLAY / AUDIO =====
        (
            "glitch_mode",
            str(CFG.get("effects", {}).get("glitch_mode", "BOTH")),
        ),  # NONE | TEXT | SCREEN | BOTH
        (
            "glitch_screen_intensity",
            float(effects.get("glitch_screen_intensity", 0.65)),
        ),  # << NOWE 0..1
        ("fps", int(disp.get("fps", FPS))),
        ("fullscreen", bool(disp.get("fullscreen", True))),
        ("ring_palette", str(disp.get("ring_palette", "auto"))),
        ("music_volume", float(audio.get("music_volume", CFG["audio"]["music_volume"]))),
        ("sfx_volume", float(audio.get("sfx_volume", CFG["audio"]["sfx_volume"]))),
        # ===== SPEED-UP =====
        ("remap_every_hits", int(rules.get("every_hits", RULE_EVERY_HITS))),
        ("spin_every_hits", int(rules.get("spin_every_hits", 5))),
        ("memory_hide_sec", float(CFG.get("memory_hide_sec", MEMORY_HIDE_AFTER_SEC))),
        # ===== TIMED =====
        ("timed_duration", float(timed.get("duration", TIMED_DURATION))),
        ("timed_gain", float(timed.get("gain", 1.0))),
        ("timed_penalty", float(timed.get("penalty", 1.0))),
        ("timed_rule_bonus", float(timed.get("rule_bonus", ADDITIONAL_RULE_TIME))),
        ("timed_difficulty", str(timed.get("difficulty", "EASY"))),
        ("timed_remap_every_hits", int(timed.get("remap_every_hits", 6))),
        ("timed_spin_every_hits", int(timed.get("spin_every_hits", 5))),
        ("timed_memory_hide_sec", float(timed.get("memory_hide_sec", MEMORY_HIDE_AFTER_SEC))),
        ("timed_mod_every_hits", int(timed.get("mod_every_hits", 6))),
        ("timed_enable_remap", bool(timed.get("allow_remap", True))),
        ("timed_enable_spin", bool(timed.get("allow_spin", True))),
        ("timed_enable_memory", bool(timed.get("allow_memory", True))),
        ("timed_enable_joystick", bool(timed.get("allow_joystick", True))),
        # ===== INNE =====
        ("levels_active", int(CFG.get("levels_active", LEVELS_ACTIVE_FOR_NOW))),
    ]


__all__ = ["settings_defaults_from_cfg"]

