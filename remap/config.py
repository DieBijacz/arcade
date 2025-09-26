# remap/config.py
from __future__ import annotations
import json, os
from typing import Dict, Any

from pathlib import Path
PKG_DIR = Path(__file__).resolve().parent

def _abs(path: str) -> str:
    # zostaw bez zmian, jeśli ktoś podał ścieżkę absolutną
    p = Path(path)
    return str(p) if p.is_absolute() else str((PKG_DIR / p).resolve())

PACKAGE_DIR = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(PACKAGE_DIR, "config.json")

DEFAULT_CFG: Dict[str, Any] = {
    "pins": {"CIRCLE": 17, "CROSS": 27, "SQUARE": 22, "TRIANGLE": 23},
    "display": {"fullscreen": True, "fps": 60, "windowed_size": [720, 1280]},
    "speedup": {"target_time_initial": 3, "target_time_min": 0.45, "target_time_step": -0.03},
    "timed": {"duration": 60.0, "rule_bonus": 5.0},
    "rules": {"every_hits": 10, "banner_sec": 2.0, "banner_font_center": 64, "banner_font_pinned": 40},
    "lives": 3,
    "audio": {"music": "assets/music.ogg", "music_volume": 0.5, "sfx_volume": 0.8},
    "effects": {"glitch_enabled": True},
    "ui": {"ring_palette": "auto"},
    "images": {
        "background": "assets/images/bg.png",
        "symbol_circle": "assets/images/circle.png",
        "symbol_cross": "assets/images/cross.png",
        "symbol_square": "assets/images/square.png",
        "symbol_triangle": "assets/images/triangle.png",
        "arrow": "assets/images/arrow.png",
        "ring": "assets/images/ring.png",
    },
    "highscore": 0,
    "levels": {},
}

def _deepcopy(obj): 
    return json.loads(json.dumps(obj))

def _merge(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v
    return dst

def _sanitize_cfg(cfg: dict) -> dict:
    s = cfg["speedup"]
    s["target_time_initial"] = float(max(0.2, min(10.0, s["target_time_initial"])))
    s["target_time_min"]     = float(max(0.1, min(s["target_time_initial"], s["target_time_min"])))
    s["target_time_step"]    = float(max(-1.0, min(1.0, s["target_time_step"])))
    a = cfg.setdefault("audio", {})
    a["music_volume"] = float(max(0.0, min(1.0, a.get("music_volume", 0.5))))
    a["sfx_volume"]   = float(max(0.0, min(1.0, a.get("sfx_volume",   0.8))))
    cfg["lives"] = int(max(0, min(9, cfg["lives"])))
    if "fps" in cfg["display"]:
        cfg["display"]["fps"] = int(max(30, min(240, cfg["display"]["fps"])))
    ws = cfg["display"].get("windowed_size", [720, 1280])
    if isinstance(ws, (list, tuple)) and len(ws) == 2 and all(isinstance(x, (int, float)) for x in ws):
        w, h = max(200, min(10000, int(ws[0]))), max(200, min(10000, int(ws[1])))
        cfg["display"]["windowed_size"] = [w, h]
    else:
        cfg["display"]["windowed_size"] = [720, 1280]
    r = cfg.setdefault("rules", {})
    r["banner_font_center"] = int(max(8, min(200, r.get("banner_font_center", 64))))
    r["banner_font_pinned"] = int(max(8, min(200, r.get("banner_font_pinned", 40))))

    for section in ("images", "audio"):
        d = cfg.get(section, {})
        for k, v in list(d.items()):
            if isinstance(v, str):
                d[k] = _abs(v)
    cfg["config_path"] = str(Path(CONFIG_PATH).resolve())
    return cfg

def save_config(partial_cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            base = json.load(f)
        if not isinstance(base, dict): base = {}
    except Exception:
        base = {}
    merged = _merge(base, partial_cfg)
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def load_config() -> dict:
    cfg = _deepcopy(DEFAULT_CFG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user = json.load(f)
        _merge(cfg, user)
    except FileNotFoundError:
        save_config(cfg)
    except Exception:
        pass
    cfg = _sanitize_cfg(cfg)

    for section in ("images", "audio"):
        d = cfg.get(section, {})
        for k, v in list(d.items()):
            if isinstance(v, str):
                d[k] = _abs(v)
    cfg["config_path"] = str(Path(CONFIG_PATH).resolve())
    return cfg

def persist_windowed_size(width: int, height: int) -> None:
    try:
        cfg = load_config()
        cfg.setdefault("display", {})["windowed_size"] = [int(width), int(height)]
        save_config({"display": {"windowed_size": cfg["display"]["windowed_size"]}})
    except Exception:
        pass

CFG = load_config()
