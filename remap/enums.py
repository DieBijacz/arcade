from enum import Enum

class GlitchMode(str, Enum):
    NONE   = "NONE"
    TEXT   = "TEXT"
    SCREEN = "SCREEN"
    BOTH   = "BOTH"