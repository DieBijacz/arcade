from __future__ import annotations

from collections import deque
from typing import Deque, List


class InputQueue:
    def __init__(self) -> None:
        self._q: Deque[str] = deque()

    def push(self, name: str) -> None:
        self._q.append(name)

    def pop_all(self) -> list[str]:
        out: List[str] = list(self._q)
        self._q.clear()
        return out


__all__ = ["InputQueue"]

