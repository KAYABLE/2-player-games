import random
import time

PLAYERS = ("P1", "P2")
COLORS = ("red", "green", "blue")
NAMES = {"P1": "PLAYER 1", "P2": "PLAYER 2"}

COUNTDOWN_S = 3
WAIT_MIN_S = 2.0
WAIT_MAX_S = 5.0
DRAW_TIMEOUT_S = 3.0


def pause(seconds, stop):
    """Sleep, but return False early if the game was stopped."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if stop.is_set():
            return False
        time.sleep(0.01)
    return True


def lobby(board, notify, stop):
    """Both players press any button on their board to get ready."""
    notify("mode", "lobby")
    board.lobby()
    ready = {p: False for p in PLAYERS}
    notify("lobby", dict(ready))

    while not all(ready.values()):
        if stop.is_set():
            return False
        for player, kind, _, _ in board.read_events():
            if kind == "READY" and not ready[player]:
                ready[player] = True
                notify("lobby", dict(ready))
        time.sleep(0.01)
    return True


def judge(event, targets, disqualified, reactions, notify):
    player, kind, color, ms = event
    if player in disqualified or player in reactions:
        return
    if kind == "EARLY":
        disqualified.add(player)
        notify("status", {"player": player, "text": "FIRED TOO EARLY"})
    elif kind == "PRESS":
        if color != targets.get(player):
            disqualified.add(player)
            notify("status", {"player": player, "text": "WRONG BUTTON"})
        else:
            reactions[player] = ms
            notify("reaction", {"player": player, "ms": ms})


def decide(disqualified, reactions):
    if reactions:
        winner = min(reactions, key=reactions.get)
        return f"{NAMES[winner]} WINS!"
    if len(disqualified) == len(PLAYERS):
        return "BOTH PLAYERS DISQUALIFIED"
    return "NO VALID SHOT"


def run_duel(board, notify, stop, reveal_at_draw):
    """
    Shared round logic for both standoff versions.
      reveal_at_draw=False: one colour is called before the countdown (version 1)
      reveal_at_draw=True:  each player gets a random colour at the draw (version 2)
    """
    if not lobby(board, notify, stop):
        return None

    notify("mode", "game")
    notify("round", None)
    board.reset()

    if reveal_at_draw:
        targets = {}
        notify("panels", {p: None for p in PLAYERS})
    else:
        called = random.choice(COLORS)
        targets = {p: called for p in PLAYERS}
        notify("panels", dict(targets))

    if not reveal_at_draw:
        notify("message", f"{called.upper()}!")
        notify("status", {"player": "P1", "text": f"PRESS {called.upper()}"})
        notify("status", {"player": "P2", "text": f"PRESS {called.upper()}"})
        if not pause(2, stop):
            return None

    notify("message", "READY")
    if not pause(1, stop):
        return None

    # Random wait: presses now are EARLY
    board.wait()
    disqualified, reactions = set(), {}
    wait_end = time.monotonic() + random.uniform(WAIT_MIN_S, WAIT_MAX_S)
    while time.monotonic() < wait_end:
        if stop.is_set():
            board.reset()
            return None
        for event in board.read_events():
            judge(event, targets, disqualified, reactions, notify)
        if len(disqualified) == len(PLAYERS):
            break
        time.sleep(0.005)

    # DRAW
    if len(disqualified) < len(PLAYERS):
        if reveal_at_draw:
            targets = {p: random.choice(COLORS) for p in PLAYERS}
            notify("panels", dict(targets))
        notify("message", "DRAW!!!")
        board.go()

        deadline = time.monotonic() + DRAW_TIMEOUT_S
        while time.monotonic() < deadline and not stop.is_set():
            for event in board.read_events():
                judge(event, targets, disqualified, reactions, notify)
            if all(p in disqualified or p in reactions for p in PLAYERS):
                break
            time.sleep(0.005)

    board.reset()
    result = decide(disqualified, reactions)
    notify("result", result)
    return result