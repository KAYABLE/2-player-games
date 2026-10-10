# esp32/main.py  (MicroPython, same file on both boards)
# Job: connect over USB and/or WiFi, report button presses, blink LED on IDENT.
# The Pi decides everything else. Press times are measured from the GO command.

import sys
import select
import socket
import time
import network
import machine
import ubinascii
from machine import Pin

# ---- fill these in for network mode (leave empty for USB only) ----
WIFI_SSID = ""
WIFI_PASSWORD = ""

TCP_PORT = 4200
BEACON_PORT = 4210
BEACON_EVERY_MS = 1000
DEBOUNCE_MS = 25

IDLE, LOBBY, WAIT, GO = range(4)

state = IDLE
go_us = 0
reported = set()          # colours already reported in this state
buttons = {}              # colour -> Pin
debounce = {}             # colour -> [stable, pending_ms, pending_us, pending]
led = Pin(25, Pin.OUT)

uid = ubinascii.hexlify(machine.unique_id()).decode()[-6:]
poller = select.poll()
poller.register(sys.stdin, select.POLLIN)

server = None
udp = None
client = None
net_buf = ""
last_beacon = 0


def send(line):
    print(line)                              # USB
    global client
    if client:                               # network
        try:
            client.send((line + "\n").encode())
        except OSError:
            client.close()
            client = None


def set_state(new):
    global state
    state = new
    reported.clear()


def blink(times):
    for _ in range(times):
        led.value(1)
        time.sleep_ms(120)
        led.value(0)
        time.sleep_ms(120)


def configure(args):
    global led
    red, green, blue, led_pin = [int(x) for x in args[:4]]
    buttons.clear()
    debounce.clear()
    for colour, pin_no in (("red", red), ("green", green), ("blue", blue)):
        buttons[colour] = Pin(pin_no, Pin.IN, Pin.PULL_UP)
        debounce[colour] = [1, 0, 0, False]
    led = Pin(led_pin, Pin.OUT)
    led.value(0)


def handle(line):
    global go_us
    parts = line.split()
    if not parts:
        return
    cmd = parts[0]
    if cmd == "CONFIG" and len(parts) >= 5:
        configure(parts[1:5])
    elif cmd == "IDENT":
        blink(3)
    elif cmd == "LOBBY":
        set_state(LOBBY)
    elif cmd == "WAIT":
        set_state(WAIT)
    elif cmd == "GO":
        go_us = time.ticks_us()
        set_state(GO)
    elif cmd == "RESET":
        set_state(IDLE)


def on_press(colour, t_us):
    if colour in reported:
        return
    if state == LOBBY:
        reported.add(colour)
        send("READY " + colour)
    elif state == WAIT:
        reported.add(colour)
        send("EARLY " + colour)
    elif state == GO:
        reported.add(colour)
        diff = time.ticks_diff(t_us, go_us)
        if diff < 0:                          # pressed just before GO arrived
            send("EARLY " + colour)
        else:
            send("PRESS %s %d" % (colour, diff))


def scan_buttons():
    now = time.ticks_ms()
    for colour, pin in buttons.items():
        d = debounce[colour]
        raw = pin.value()
        if raw != d[0]:
            if not d[3]:
                d[1] = now
                d[2] = time.ticks_us()        # timestamp at first edge
                d[3] = True
            elif time.ticks_diff(now, d[1]) >= DEBOUNCE_MS:
                d[0] = raw
                d[3] = False
                if raw == 0:                  # pressed (pull-up, active low)
                    on_press(colour, d[2])
        else:
            d[3] = False


def read_usb():
    while poller.poll(0):
        line = sys.stdin.readline()
        if not line:
            break
        handle(line.strip())


def connect_wifi():
    global server, udp
    if not WIFI_SSID:
        return
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    t0 = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), t0) > 15000:
            print("WIFI FAILED")
            return
        time.sleep_ms(200)

    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", TCP_PORT))
    server.listen(1)
    server.setblocking(False)

    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    print("IP", wlan.ifconfig()[0])


def accept_client():
    global client, net_buf
    if client is None and server:
        try:
            c, _ = server.accept()
            c.setblocking(False)
            client = c
            net_buf = ""
        except OSError:
            pass                              # nobody connecting


def read_net():
    global client, net_buf
    if client is None:
        return
    try:
        data = client.recv(128)
    except OSError:
        return                                # no data yet
    if not data:                              # Pi disconnected
        client.close()
        client = None
        set_state(IDLE)
        return
    net_buf += data.decode()
    while "\n" in net_buf:
        line, net_buf = net_buf.split("\n", 1)
        handle(line.strip())


def beacon():
    global last_beacon
    if udp is None:
        return
    now = time.ticks_ms()
    if time.ticks_diff(now, last_beacon) >= BEACON_EVERY_MS:
        last_beacon = now
        try:
            udp.sendto(("STANDOFF_BOARD " + uid).encode(),
                       ("255.255.255.255", BEACON_PORT))
        except OSError:
            pass


def main():
    connect_wifi()
    print("BOOT", uid)
    while True:
        read_usb()
        accept_client()
        read_net()
        scan_buttons()
        beacon()
        time.sleep_ms(1)


main()