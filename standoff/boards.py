import queue
import socket
import threading
import time

PLAYERS = ("P1", "P2")
BOARD_PORT = 4200      # ESP32 TCP server (network mode)
BEACON_PORT = 4210     # ESP32 UDP beacons (discovery)
BAUD = 115200


def split_lines(buf):
    lines = []
    while b"\n" in buf:
        line, buf = buf.split(b"\n", 1)
        lines.append(line.decode(errors="ignore").strip())
    return lines, buf


# ---------- transports: both speak the same line protocol ----------

class SerialLink:
    """USB: one ESP32 on a COM / tty port."""

    def __init__(self, port):
        import serial
        self.ser = serial.Serial(port, BAUD, timeout=0)
        time.sleep(2)                       # opening the port resets the ESP32
        self.ser.reset_input_buffer()
        self.buf = b""

    def send(self, line):
        self.ser.write((line + "\n").encode())

    def read_lines(self):
        if self.ser.in_waiting:
            self.buf += self.ser.read(self.ser.in_waiting)
        lines, self.buf = split_lines(self.buf)
        return lines

    def close(self):
        self.ser.close()


class SocketLink:
    """Network: one ESP32 reached over TCP at its IP address."""

    def __init__(self, ip):
        self.sock = socket.create_connection((ip, BOARD_PORT), timeout=3)
        self.sock.setblocking(False)
        self.buf = b""

    def send(self, line):
        self.sock.sendall((line + "\n").encode())

    def read_lines(self):
        try:
            data = self.sock.recv(256)
        except BlockingIOError:
            data = None
        if data == b"":
            raise ConnectionError("board closed the connection")
        if data:
            self.buf += data
        lines, self.buf = split_lines(self.buf)
        return lines

    def close(self):
        self.sock.close()


# ---------- discovery ----------

class Discovery:
    """Listens for UDP beacons from ESP32s on the network."""

    def __init__(self):
        self.found = {}
        self.lock = threading.Lock()
        threading.Thread(target=self._listen, daemon=True).start()

    def _listen(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("", BEACON_PORT))
        while True:
            data, addr = s.recvfrom(256)
            if data.startswith(b"STANDOFF_BOARD"):
                parts = data.decode(errors="ignore").split()
                uid = parts[1] if len(parts) > 1 else "?"
                with self.lock:
                    self.found[addr[0]] = {"ip": addr[0], "id": uid, "seen": time.time()}

    def network_boards(self):
        now = time.time()
        with self.lock:
            return [b for b in self.found.values() if now - b["seen"] < 5]


def serial_ports():
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except Exception:
        return []


# ---------- boards: what standoff games talk to ----------
# Every board has: lobby(), wait(), go(), reset(), read_events(), close()
# read_events() returns (player, kind, colour, ms) with kind in READY, EARLY, PRESS.

class WebBoard:
    """Emulated buttons. The browser posts key presses to /api/press."""

    def __init__(self):
        self.q = queue.Queue()
        self.state = "idle"
        self.go_t = None
        self.reported = set()

    def press(self, player, color):
        self.q.put((player, color, time.monotonic()))

    def _set(self, state):
        self.state = state
        self.reported = set()

    def lobby(self):
        self._set("lobby")

    def wait(self):
        self._set("wait")

    def go(self):
        self.go_t = time.monotonic()
        self._set("go")

    def reset(self):
        self._set("idle")
        while not self.q.empty():
            self.q.get_nowait()

    def read_events(self):
        out = []
        while True:
            try:
                player, color, t = self.q.get_nowait()
            except queue.Empty:
                break
            if self.state == "idle" or player in self.reported:
                continue
            if self.state == "lobby":
                kind, ms = "READY", None
            elif self.state == "wait" or self.go_t is None or t < self.go_t:
                kind, ms = "EARLY", None
            else:
                kind, ms = "PRESS", (t - self.go_t) * 1000
            self.reported.add(player)
            out.append((player, kind, color, ms))
        return out

    def close(self):
        pass


class HardwareBoard:
    """Real ESP32s. links = {"P1": link, "P2": link}."""

    def __init__(self, links, pins):
        self.links = links
        for p, link in links.items():
            pin = pins[p]
            link.send(f"CONFIG {pin['red']} {pin['green']} {pin['blue']} {pin['led']}")
            link.send("IDENT")              # blink the LED so you can see it's connected

    def _all(self, msg):
        for link in self.links.values():
            link.send(msg)

    def lobby(self):
        self._all("LOBBY")

    def wait(self):
        self._all("WAIT")

    def go(self):
        self._all("GO")

    def reset(self):
        self._all("RESET")

    def close(self):
        for link in self.links.values():
            link.close()

    def read_events(self):
        out = []
        for player, link in self.links.items():
            for line in link.read_lines():
                parts = line.split()
                if not parts:
                    continue
                kind = parts[0]
                if kind in ("READY", "EARLY") and len(parts) >= 2:
                    out.append((player, kind, parts[1], None))
                elif kind == "PRESS" and len(parts) >= 3:
                    out.append((player, "PRESS", parts[1], int(parts[2]) / 1000))
        return out