from games.common import run_duel

NAME = "Standoff 2: Reveal at Draw"
DESCRIPTION = "Each player's colour appears at the draw. Fastest correct press wins."


def play(board, notify, stop):
    return run_duel(board, notify, stop, reveal_at_draw=True)