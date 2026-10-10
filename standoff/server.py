import copy
import json
import os
import threading

from flask import Flask, jsonify, render_template, request

from boards import (Discovery, HardwareBoard, SerialLink, SocketLink,
                    WebBoard, serial_ports)
from games import standoff1, standoff2
from games.common import PLAYERS
from games import russian_roulette

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(HERE, "settings.json")

GAMES = {
    "standoff1": standoff1,
    "standoff2": standoff2,
    "russian_roulette": russian_roulette,   # add later
}

DEFAULT_SETTINGS = {
    "emulate": False,
    "connection": "network",                 # "usb" or "network"
    "boards": {
        "P1": {"target": "", "pins": {"red": 4, "green": 16, "blue": 17, "led": 25}},
        "P2": {"target": "", "pins": {"red": 18, "green": 19, "blue": 21, "led": 22}},
    },
    "keys": {"P1": ["a", "s", "d"], "P2": [";", "l", "k"]},   # red, green, blue
}


def merge(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merge(base[k], v)
        else:
            base[k] = v
    return base


PLAYERS_LIST = ("P1", "P2")

def sanitize(settings):
    """Repair settings files left over from older versions."""
    for p in PLAYERS_LIST:
        keys = settings["keys"].get(p)
        if not isinstance(keys, list) or len(keys) != 3:
            settings["keys"][p] = list(DEFAULT_SETTINGS["keys"][p])
        if not isinstance(settings["boards"][p].get("pins"), dict):
            settings["boards"][p]["pins"] = dict(DEFAULT_SETTINGS["boards"][p]["pins"])
    return settings


def load_settings():
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            merge(settings, json.load(f))
    return sanitize(settings)


def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


discovery = Discovery()


class Session:
    def __init__(self):
        self.lock = threading.Lock()
        self.settings = load_settings()
        self.view = self._blank("")
        self.board = None
        self.stop_event = None
        self.thread = None

    @staticmethod
    def _blank(game_id):
        return {
            "mode": "menu", "game": game_id,
            "ready": {p: False for p in PLAYERS},
            "panels": {p: None for p in PLAYERS},
            "message": "", "msg_id": 0,
            "status": {}, "reactions": {}, "result": None,
        }

    # called by the game thread
    def notify(self, kind, payload):
        with self.lock:
            v = self.view
            if kind == "mode":
                v["mode"] = payload
            elif kind == "lobby":
                v["ready"] = payload
            elif kind == "round":
                v.update(status={}, reactions={}, result=None, message="",
                         panels={p: None for p in PLAYERS})
            elif kind == "panels":
                v["panels"] = payload
            elif kind == "message":
                v["message"] = payload
                v["msg_id"] += 1
            elif kind == "status":
                v["status"][payload["player"]] = payload["text"]
            elif kind == "reaction":
                v["reactions"][payload["player"]] = payload["ms"]
            elif kind == "result":
                v["result"] = payload

    def _run(self, game, board, stop):
        try:
            while not stop.is_set():
                game.play(board, self.notify, stop)
                if stop.wait(4):                # show the result, then lobby again
                    break
        finally:
            board.close()
            with self.lock:
                self.view["mode"] = "menu"

    def _make_board(self):
        s = self.settings
        if s["emulate"]:
            return WebBoard()
        links = {}
        for p in PLAYERS:
            target = s["boards"][p]["target"]
            if not target:
                raise RuntimeError(f"{p} has no board selected")
            if s["connection"] == "usb":
                links[p] = SerialLink(target)
            else:
                links[p] = SocketLink(target)
        pins = {p: s["boards"][p]["pins"] for p in PLAYERS}
        return HardwareBoard(links, pins)

    def start(self, game_id):
        if self.thread and self.thread.is_alive():
            return "A game is already running"
        game = GAMES.get(game_id)
        if game is None:
            return "Unknown game"
        try:
            board = self._make_board()
        except Exception as e:
            return f"Could not connect: {e}"

        with self.lock:
            self.view = self._blank(game_id)
            self.view["mode"] = "lobby"
        self.board = board
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=self._run, args=(game, board, self.stop_event), daemon=True)
        self.thread.start()
        return None

    def stop(self):
        if self.stop_event:
            self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)

    def press(self, player, color):
        if isinstance(self.board, WebBoard):
            self.board.press(player, color)


session = Session()
app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/games")
def games():
    return jsonify([{"id": k, "name": m.NAME, "description": m.DESCRIPTION}
                    for k, m in GAMES.items()])


@app.get("/api/state")
def state():
    with session.lock:
        data = copy.deepcopy(session.view)
    data["emulate"] = session.settings["emulate"]
    data["keys"] = session.settings["keys"]
    return jsonify(data)


@app.post("/api/start")
def start():
    return jsonify(error=session.start(request.get_json()["game"]))


@app.post("/api/stop")
def stop():
    session.stop()
    return jsonify(ok=True)


@app.post("/api/press")
def press():
    data = request.get_json()
    session.press(data["player"], data["color"])
    return jsonify(ok=True)


@app.get("/api/discover")
def discover():
    if session.settings["connection"] == "usb":
        items = [{"target": p, "label": p} for p in serial_ports()]
    else:
        items = [{"target": b["ip"], "label": f"{b['ip']}  (board {b['id']})"}
                 for b in discovery.network_boards()]
    return jsonify(items)


@app.get("/api/settings")
def get_settings():
    return jsonify(session.settings)


@app.post("/api/settings")
def post_settings():
    session.settings = sanitize(request.get_json())
    save_settings(session.settings)
    return jsonify(session.settings)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)