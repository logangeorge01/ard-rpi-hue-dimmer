#!/usr/bin/env python3
"""Pair with a Hue bridge and write ~/.hue.env for hue_button.py.

Usage: python3 pair.py [bridge-ip]
Finds the bridge automatically if no IP is given, then waits for you to press
its link button.
"""
import json
import os
import ssl
import sys
import time
import urllib.request

ENV_FILE = os.path.expanduser(os.environ.get("HUE_ENV", "~/.hue.env"))
CTX = ssl._create_unverified_context()  # the bridge uses a self-signed certificate
WAIT = 90


def discover():
    with urllib.request.urlopen("https://discovery.meethue.com/", timeout=10) as r:
        bridges = json.load(r)
    if not bridges:
        raise SystemExit("no bridge found; pass its IP: python3 pair.py <bridge-ip>")
    if len(bridges) > 1:
        print("found several bridges, using the first:", [b["internalipaddress"] for b in bridges])
    return bridges[0]["internalipaddress"]


def request_key(bridge):
    body = json.dumps({"devicetype": "ard-rpi-hue-dimmer#pi", "generateclientkey": True}).encode()
    req = urllib.request.Request(f"https://{bridge}/api", data=body, method="POST")
    with urllib.request.urlopen(req, context=CTX, timeout=5) as r:
        return json.load(r)[0]


def entertainment_areas(bridge, key):
    req = urllib.request.Request(
        f"https://{bridge}/clip/v2/resource/entertainment_configuration",
        headers={"hue-application-key": key},
    )
    with urllib.request.urlopen(req, context=CTX, timeout=5) as r:
        return [c["metadata"]["name"] for c in json.load(r)["data"]]


def main():
    if os.path.exists(ENV_FILE) and "--force" not in sys.argv:
        raise SystemExit(f"{ENV_FILE} already exists; rerun with --force to replace it")
    args = [a for a in sys.argv[1:] if a != "--force"]
    bridge = args[0] if args else discover()
    print(f"bridge: {bridge}\npress the link button on the bridge (waiting {WAIT}s)...")

    deadline = time.monotonic() + WAIT
    while True:
        result = request_key(bridge)
        if "success" in result:
            break
        if result.get("error", {}).get("type") != 101:  # 101 = link button not pressed
            raise SystemExit(f"bridge error: {result}")
        if time.monotonic() > deadline:
            raise SystemExit("timed out waiting for the link button")
        time.sleep(2)

    key, clientkey = result["success"]["username"], result["success"]["clientkey"]
    fd = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"HUE_BRIDGE={bridge}\nHUE_KEY={key}\nHUE_CLIENTKEY={clientkey}\n")
    print(f"saved {ENV_FILE}")

    areas = entertainment_areas(bridge, key)
    if areas:
        print(f"entertainment areas: {areas} (first is used unless you add HUE_AREA=<name> to {ENV_FILE})")
    else:
        print("no entertainment areas yet: create one in the Hue app (needed for the knob)")


if __name__ == "__main__":
    main()
