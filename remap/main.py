from __future__ import annotations

import os
import sys

import pygame

from .config import CFG
from .constants import FPS
from .game import Game
from .gpio import init_gpio
from .input_queue import InputQueue
from .models import Mode

# ========= GAME =========
# ============================== MAIN LOOP ============================== #
def main():
    os.environ['SDL_VIDEO_WINDOW_POS'] = "0,0"
    pygame.init()
    pygame.key.set_repeat()
    fullscreen = bool(CFG.get("display", {}).get("fullscreen", True))
    screen = pygame.display.set_mode((1, 1))  # tiny placeholder; real size set next
    game = Game(screen, mode=Mode.SPEEDUP)
    game._set_display_mode(fullscreen)
    pygame.display.set_caption("Remap")
    iq = InputQueue()
    _ = init_gpio(iq)

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit(0)
            game.handle_event(event, iq)
        game.update(iq)
        game.draw()
        game.clock.tick(int(game.settings.get("fps", FPS)))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pygame.quit(); sys.exit(0)

