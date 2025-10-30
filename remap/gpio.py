from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Dict, TYPE_CHECKING

from .config import CFG

if TYPE_CHECKING:
    from .input_queue import InputQueue


GPIO_AVAILABLE = True
IS_WINDOWS = sys.platform.startswith("win")
try:
    from gpiozero import Button  # type: ignore
except Exception:  # pragma: no cover - gpiozero is optional
    GPIO_AVAILABLE = False
    Button = None  # type: ignore


@dataclass
class Pins:
    CIRCLE: int
    CROSS: int
    SQUARE: int
    TRIANGLE: int


PINS = Pins(**CFG["pins"])

GPIO_PULL_UP = True
GPIO_BOUNCE_TIME = 0.05


def init_gpio(iq: "InputQueue") -> Dict[str, Button]:
    if IS_WINDOWS or not GPIO_AVAILABLE or Button is None:
        return {}
    pins = {
        "CIRCLE": PINS.CIRCLE,
        "CROSS": PINS.CROSS,
        "SQUARE": PINS.SQUARE,
        "TRIANGLE": PINS.TRIANGLE,
    }
    buttons = {
        name: Button(pin, pull_up=GPIO_PULL_UP, bounce_time=GPIO_BOUNCE_TIME)
        for name, pin in pins.items()
    }
    for name, btn in buttons.items():
        btn.when_pressed = (lambda n=name: iq.push(n))
    return buttons


__all__ = [
    "GPIO_AVAILABLE",
    "IS_WINDOWS",
    "Pins",
    "PINS",
    "GPIO_PULL_UP",
    "GPIO_BOUNCE_TIME",
    "init_gpio",
]

