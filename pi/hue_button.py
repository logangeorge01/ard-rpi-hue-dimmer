#!/usr/bin/env python3
"""Toggle Hue lights on button presses and dim them with the knob, via the Uno.

The knob streams brightness through the Entertainment API so all lights change
together and smoothly; when the knob stops, the final level is saved via REST.
"""
import http.client
import json
import os
import ssl
import time

import serial

from hue_stream import HueStream

ENV_FILE = os.path.expanduser(os.environ.get("HUE_ENV", "~/.hue.env"))


def load_env(path):
    """Read KEY=value lines (as written by pair.py); real environment variables win."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


load_env(ENV_FILE)
missing = [k for k in ("HUE_BRIDGE", "HUE_KEY", "HUE_CLIENTKEY") if not os.environ.get(k)]
if missing:
    raise SystemExit(f"missing {', '.join(missing)}: run pair.py or fill in {ENV_FILE}")

BRIDGE = os.environ["HUE_BRIDGE"]
KEY = os.environ["HUE_KEY"]
CLIENTKEY = os.environ["HUE_CLIENTKEY"]
PORT = os.environ.get("BUTTON_PORT", "/dev/ttyACM0")
AREA_NAME = os.environ.get("HUE_AREA")  # default: the first entertainment area

FRAME_INTERVAL = 0.04  # 25 frames/sec
EASE = 0.35            # fraction of the remaining gap to close each frame
EASE_START = 0.08      # gentler catch-up when the knob is first touched (~1s)
CAUGHT_UP = 0.03       # switch to normal easing once this close to the knob
CURVE = 1.8            # >1 gives the low end of the knob finer control
IDLE_STOP = 2.0        # seconds without knob movement before streaming stops
OFF_BELOW = 2          # knob at 0-1% turns the lights off
WHITE_XY = (0.3127, 0.3290)

# The bridge uses a self-signed certificate.
CTX = ssl._create_unverified_context()

_conn = None


def hue(method, path, body=None):
    # Reuse one connection; a fresh TLS handshake per request is slow on a Pi 3.
    global _conn
    for attempt in range(2):
        if _conn is None:
            _conn = http.client.HTTPSConnection(BRIDGE, context=CTX, timeout=5)
        try:
            _conn.request(
                method,
                f"/clip/v2/resource/{path}",
                body=json.dumps(body) if body is not None else None,
                headers={"hue-application-key": KEY, "Content-Type": "application/json"},
            )
            resp = _conn.getresponse()
            data = json.load(resp)
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}: {data}")
            return data
        except (http.client.HTTPException, OSError):
            # The bridge closed an idle connection; reconnect and retry once.
            _conn.close()
            _conn = None
            if attempt:
                raise


def find_area():
    areas = hue("GET", "entertainment_configuration")["data"]
    names = [c["metadata"]["name"] for c in areas]
    if not areas:
        raise SystemExit("no entertainment areas on the bridge: create one in the Hue app")
    if AREA_NAME is None:
        print(f"using entertainment area {names[0]!r} (set HUE_AREA to pick from {names})", flush=True)
        return areas[0]
    for c in areas:
        if c["metadata"]["name"] == AREA_NAME:
            return c
    raise SystemExit(f"no entertainment area named {AREA_NAME!r}; found {names}")


def all_lights_group():
    for g in hue("GET", "grouped_light")["data"]:
        if g["owner"]["rtype"] == "bridge_home":
            return g["id"]
    raise RuntimeError("no bridge_home group")


def knob_level(pct):
    return 0.0 if pct < OFF_BELOW else (pct / 100) ** CURVE


def toggle_all(group, knob_pct):
    lights = hue("GET", "light")["data"]
    if any(l["on"]["on"] for l in lights):
        hue("PUT", f"grouped_light/{group}", {"on": {"on": False}})
        print("lights off", flush=True)
        return
    # Turn on at the knob's brightness (unless the knob is at off, then use the last level).
    body = {"on": {"on": True}}
    if knob_pct is not None and knob_level(knob_pct) > 0:
        body["dimming"] = {"brightness": max(round(knob_level(knob_pct) * 100, 1), 0.5)}
    hue("PUT", f"grouped_light/{group}", body)
    print(f"lights on (knob {knob_pct}%)", flush=True)


def save_brightness(group, level):
    if level <= 0:
        hue("PUT", f"grouped_light/{group}", {"on": {"on": False}})
        print("saved: off", flush=True)
        return
    pct = max(round(level * 100, 1), 0.5)  # below ~0.5 the bulbs just sit at their minimum
    hue("PUT", f"grouped_light/{group}", {"on": {"on": True}, "dimming": {"brightness": pct}})
    print(f"saved brightness {pct}%", flush=True)


class KnobStream:
    """Streams a brightness level to every channel of an entertainment area."""

    def __init__(self, area):
        self.area = area
        self.stream = None
        self.level = 0.0
        self.target = 0.0
        self.catching_up = False
        self.last_frame = 0.0
        self.last_move = 0.0
        self.colors = {}

    @property
    def active(self):
        return self.stream is not None

    def channel_colors(self):
        # Channel -> entertainment service -> device -> light, to keep each light's color.
        ent_owner = {e["id"]: e["owner"]["rid"] for e in hue("GET", "entertainment")["data"]}
        lights = {l["owner"]["rid"]: l for l in hue("GET", "light")["data"]}
        colors, levels = {}, []
        for ch in self.area["channels"]:
            light = lights.get(ent_owner.get(ch["members"][0]["service"]["rid"]))
            xy = WHITE_XY
            if light and "color" in light:
                xy = (light["color"]["xy"]["x"], light["color"]["xy"]["y"])
            colors[ch["channel_id"]] = xy
            if light:
                levels.append(light["dimming"]["brightness"] / 100 if light["on"]["on"] else 0.0)
        return colors, (max(levels) if levels else 0.0)

    def move(self, pct):
        if not self.active:
            self.colors, self.level = self.channel_colors()
            hue("PUT", f"entertainment_configuration/{self.area['id']}", {"action": "start"})
            self.stream = HueStream(BRIDGE, KEY, CLIENTKEY, self.area["id"])
            self.catching_up = True
            print("streaming started", flush=True)
        self.target = knob_level(pct)
        self.last_move = time.monotonic()

    def tick(self):
        """Send a frame if one is due. Returns True once the knob has been idle long enough."""
        if not self.active:
            return False
        now = time.monotonic()
        if now - self.last_frame >= FRAME_INTERVAL:
            if self.catching_up and abs(self.target - self.level) < CAUGHT_UP:
                self.catching_up = False
            self.level += (self.target - self.level) * (EASE_START if self.catching_up else EASE)
            if abs(self.target - self.level) < 0.002:
                self.level = self.target
            self.stream.send({ch: (x, y, self.level) for ch, (x, y) in self.colors.items()})
            self.last_frame = now
        return now - self.last_move >= IDLE_STOP

    def stop(self):
        if not self.active:
            return
        try:
            self.stream.close()
        finally:
            self.stream = None
            hue("PUT", f"entertainment_configuration/{self.area['id']}", {"action": "stop"})
            print("streaming stopped", flush=True)


def main():
    group = all_lights_group()
    knob = KnobStream(find_area())
    knob_pct = None  # last position the Uno reported
    while True:
        try:
            with serial.Serial(PORT, 9600, timeout=0.01) as ser:
                print(f"listening on {PORT}", flush=True)
                while True:
                    line = ser.readline().decode(errors="ignore").strip()
                    try:
                        if line == "PRESSED":
                            knob.stop()
                            toggle_all(group, knob_pct)
                        elif line.startswith("KNOB "):
                            knob_pct = int(line[5:])
                        elif line.startswith("DIM "):
                            knob_pct = int(line[4:])
                            knob.move(knob_pct)
                        if knob.tick():
                            level = knob.target
                            knob.stop()
                            save_brightness(group, level)
                    except Exception as e:
                        print(f"hue error: {e!r}", flush=True)
                        try:
                            knob.stop()
                        except Exception:
                            knob.stream = None
        except serial.SerialException as e:
            print(f"serial error: {e}; retrying in 5s", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
