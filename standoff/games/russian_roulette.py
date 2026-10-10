import random
from games.common import PLAYERS, NAMES, lobby, pause

NAME = "Russian Roulette"
DESCRIPTION = "Red shoots the other player, green shoots yourself, blue passes the turn."

CHAMBERS = 6
OTHER = {"P1": "P2", "P2": "P1"}


def wait_for_colour(board, shooter, stop):
    """Return the colour the shooter pressed, or None if stopped."""
    board.reset()
    board.lobby()
    while not stop.is_set():
        for player, kind, colour, _ in board.read_events():
            if player == shooter and kind == "READY":
                return colour
        pause(0.01, stop)
    return None


def play(board, notify, stop):
    if not lobby(board, notify, stop):
        return None

    notify("mode", "game")
    notify("round", None)
    notify("panels", {p: None for p in PLAYERS})

    bullet = random.randrange(CHAMBERS)     # secret, chosen once per round
    shots = 0
    shooter = "P1"

    while True:
        other = OTHER[shooter]
        notify("message", NAMES[shooter])
        notify("status", {"player": shooter,
                          "text": "RED shoot them  GREEN shoot yourself  BLUE pass"})
        notify("status", {"player": other, "text": "waiting for the other player"})

        colour = wait_for_colour(board, shooter, stop)
        if colour is None:
            board.reset()
            return None

        if colour == "blue":
            notify("message", "GAME OVER")
            board.reset()
            return None

        target = other if colour == "red" else shooter
        hit = shots == bullet
        shots += 1

        if hit:
            notify("message", "BANG!")
            winner = OTHER[target]
            notify("status", {"player": target, "text": "YOU'RE DONE"})
            notify("status", {"player": winner, "text": "SURVIVED"})
            board.reset()
            result = f"{NAMES[target]} LOSES!"
            notify("result", result)
            return result

        notify("message", "CLICK")
        notify("status", {"player": shooter, "text": f"chamber {shots}: empty"})
        if not pause(1.5, stop):
            board.reset()
            return None
        shooter = other