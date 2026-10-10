import random
from games.common import PLAYERS, NAMES, lobby, pause

NAME = "Russian Roulette"
DESCRIPTION = "One bullet, six chambers. Take turns pulling the trigger. Whoever hits the bullet loses."

CHAMBERS = 6


def play(board, notify, stop):
    if not lobby(board, notify, stop):
        return None

    notify("mode", "game")
    notify("round", None)

    bullet = random.randrange(CHAMBERS)          # the spin happens here, in secret

    for pull in range(CHAMBERS):
        shooter = PLAYERS[pull % 2]              # P1, P2, P1, ...
        for p in PLAYERS:
            notify("status", {"player": p,
                              "text": "YOUR TURN" if p == shooter else "WAIT"})
        notify("message", "PULL!")

        # wait for the shooter's button (presses from the other player are ignored)
        board.reset()
        board.lobby()
        while True:
            if stop.is_set():
                board.reset()
                return None
            events = board.read_events()
            if any(p == shooter and kind == "READY" for p, kind, _, _ in events):
                break
            pause(0.01, stop)

        if pull == bullet:
            notify("message", "BANG!")
            loser = shooter
            winner = PLAYERS[(pull + 1) % 2]
            notify("status", {"player": loser, "text": "YOU'RE DONE"})
            notify("status", {"player": winner, "text": "SURVIVED"})
            board.reset()
            result = f"{NAMES[loser]} LOSES!"
            notify("result", result)
            return result

        notify("message", "CLICK")
        notify("status", {"player": shooter, "text": f"chamber {pull + 1}: empty"})
        if not pause(random.uniform(1.0, 2.0), stop):
            board.reset()
            return None

    board.reset()                                # unreachable, but keeps the file safe
    return None