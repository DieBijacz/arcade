# remap/settings.py
from __future__ import annotations
from typing import Any, Dict

# ------------- snapshot (runtime) -------------

def make_runtime_settings(CFG: Dict[str, Any]) -> Dict[str, Any]:
    """Zbuduj słownik ustawień używany przez UI (snapshot z CFG)."""
    return {
        "target_time_initial": float(CFG["speedup"]["target_time_initial"]),
        "target_time_step":    float(CFG["speedup"]["target_time_step"]),
        "target_time_min":     float(CFG["speedup"]["target_time_min"]),
        "lives":               int(CFG["lives"]),
        "glitch_enabled":      bool(CFG.get("effects", {}).get("glitch_enabled", True)),
        "music_volume":        float(CFG["audio"]["music_volume"]),
        "sfx_volume":          float(CFG["audio"]["sfx_volume"]),
        "fullscreen":          bool(CFG["display"]["fullscreen"]),
        "timed_rule_bonus":    float(CFG["timed"].get("rule_bonus", 5.0)),
        "rule_font_center":    int(CFG["rules"].get("banner_font_center", 64)),
        "rule_font_pinned":    int(CFG["rules"].get("banner_font_pinned", 40)),
        "ring_palette":        str(CFG.get("ui", {}).get("ring_palette", "auto")),
    }

# ------------- clamp (na żywo w UI) -------------

def clamp_settings(s: Dict[str, Any]) -> None:
    """Zaciska zakresy – spójne z _sanitize_cfg() z remap/config.py."""
    s["target_time_initial"] = max(0.2, min(10.0, float(s.get("target_time_initial", 3))))
    s["target_time_min"]     = max(0.1, min(float(s["target_time_initial"]), float(s.get("target_time_min", 0.45))))
    s["target_time_step"]    = max(-1.0, min(1.0, float(s.get("target_time_step", -0.03))))
    s["lives"]               = max(0, min(9, int(s.get("lives", 3))))
    s["music_volume"]        = max(0.0, min(1.0, float(s.get("music_volume", 0.5))))
    s["sfx_volume"]          = max(0.0, min(1.0, float(s.get("sfx_volume",   0.8))))
    s["timed_rule_bonus"]    = max(0.0, min(30.0, float(s.get("timed_rule_bonus", 5.0))))
    s["rule_font_center"]    = max(8,  min(200, int(s.get("rule_font_center", 64))))
    s["rule_font_pinned"]    = max(8,  min(200, int(s.get("rule_font_pinned", 40))))
    # bool/str zostawiamy bez zmian

# ------------- zapis do config.json  -------------

def commit_settings(
    settings: Dict[str, Any],
    *,
    CFG: Dict[str, Any],
    LEVELS: Dict[int, Any],
    TIMED_DURATION: float,
    WINDOWED_DEFAULT_SIZE: tuple[int, int],
    RULE_EVERY_HITS: int,
) -> Dict[str, Any]:
    """
    Aktualizuje CFG w pamięci i buduje payload do save_config().
    Zwraca słownik, który przekazujesz do remap.config.save_config().
    """
    clamp_settings(settings)
    s = settings

    # 1) aktualizacja CFG (runtime)
    CFG["speedup"].update(
        {
            "target_time_initial": float(s["target_time_initial"]),
            "target_time_step":    float(s["target_time_step"]),
            "target_time_min":     float(s["target_time_min"]),
        }
    )
    CFG["lives"] = int(s["lives"])
    CFG.setdefault("effects", {})["glitch_enabled"] = bool(s.get("glitch_enabled", True))
    CFG["audio"]["music_volume"] = float(s["music_volume"])
    CFG["audio"]["sfx_volume"]   = float(s["sfx_volume"])
    CFG["display"]["fullscreen"] = bool(s["fullscreen"])
    CFG.setdefault("timed", {})["rule_bonus"] = float(s["timed_rule_bonus"])
    CFG.setdefault("rules", {})
    CFG["rules"]["banner_font_center"] = int(s["rule_font_center"])
    CFG["rules"]["banner_font_pinned"] = int(s["rule_font_pinned"])
    CFG.setdefault("ui", {})["ring_palette"] = str(s["ring_palette"])

    # 2) dump leveli (hits + kolor), ale bez narzucania struktury klas
    levels_dump: Dict[str, Any] = {}
    for lid, L in LEVELS.items():
        # spodziewamy się pól hits_required i score_color (tuple RGB)
        hits = int(getattr(L, "hits_required", 15))
        col  = tuple(getattr(L, "score_color", (235,235,235)))
        levels_dump[str(lid)] = {"hits": hits, "color": [int(col[0]), int(col[1]), int(col[2])]}

    # 3) payload do pliku (częściowy — merge w save_config)
    return {
        "speedup": CFG["speedup"],
        "lives": CFG["lives"],
        "effects": {"glitch_enabled": CFG["effects"]["glitch_enabled"]},
        "audio": {
            "music": CFG["audio"].get("music", "assets/music.ogg"),
            "music_volume": CFG["audio"]["music_volume"],
            "sfx_volume":   CFG["audio"]["sfx_volume"],
        },
        "display": {
            "fullscreen": CFG["display"]["fullscreen"],
            "fps": CFG["display"]["fps"],
            "windowed_size": CFG["display"].get("windowed_size", list(WINDOWED_DEFAULT_SIZE)),
        },
        "timed": {"rule_bonus": CFG["timed"]["rule_bonus"], "duration": CFG["timed"].get("duration", TIMED_DURATION)},
        "ui": {"ring_palette": CFG["ui"]["ring_palette"]},
        "rules": {
            "every_hits": CFG["rules"].get("every_hits", RULE_EVERY_HITS),
            "banner_font_center": CFG["rules"]["banner_font_center"],
            "banner_font_pinned": CFG["rules"]["banner_font_pinned"],
        },
        "highscore": CFG.get("highscore", 0),
        "levels": levels_dump,
    }
