from games.common import run_duel

NAME = "Standoff 1: Called Colour"
DESCRIPTION = "The colour is shown before the countdown. Fastest correct press wins."


def play(board, notify, stop):
    return run_duel(board, notify, stop, reveal_at_draw=False)