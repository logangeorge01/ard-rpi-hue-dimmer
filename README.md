# ard-rpi-hue-dimmer

dimmer potentiometer and on/off button on breadboard wired to arduino uno connected to rpi 3 communicating to philips hue bridge over wifi. didn't have female jumper wires lol so had to throw the uno in there. using hue's entertainment streaming which requires cert for encryption to send 25 req/sec to all bulbs.


## Wiring (Uno)

- Button: pin 2 and GND, on diagonal legs (uses `INPUT_PULLUP`, no resistor)
- 10K pot: outer legs to 5V and GND, wiper to A0
- Uno plugs into the Pi over USB (`/dev/ttyACM0`)

## Layout

- `arduino/button/button.ino` sends `PRESSED`, `DIM <0-100>` when the knob moves, and `KNOB <0-100>` at startup
- `pi/hue_button.py` reads the Uno. The button toggles all lights, and the knob streams brightness to an entertainment area, then saves the final level after 2s idle
- `pi/hue_stream.py` handles Hue Entertainment streaming (DTLS-PSK through the system libssl via ctypes, no pip deps)
- `pi/pair.py` finds the bridge, waits for the link button, and writes `~/.hue.env`
- `pi/install.sh` installs a systemd service for the current user that runs from this checkout

## Setup on the Pi

Requirements: Raspberry Pi OS (Bookworm/Trixie) and a Hue bridge with an entertainment area (create one in the Hue app: Settings > Entertainment areas).

```sh
sudo apt install git python3-serial
git clone https://github.com/logangeorge01/ard-rpi-hue-dimmer.git
cd ard-rpi-hue-dimmer

python3 pi/pair.py          # or: python3 pi/pair.py <bridge-ip>; then press the bridge's link button
./pi/install.sh             # installs and starts the hue-button service
journalctl -u hue-button -f # watch it
```

`~/.hue.env` holds the bridge IP and keys and is never committed (see `.env.example`). Optional settings for it:

- `HUE_AREA=<name>` sets which entertainment area the knob drives. The default is the first one on the bridge.
- `BUTTON_PORT=/dev/ttyUSB0` is for Uno clones with a CH340 USB chip. The default is `/dev/ttyACM0`.

## Flashing the Uno

With [arduino-cli](https://arduino.github.io/arduino-cli/) (`arduino-cli core install arduino:avr` once). Stop the service first, since it holds the serial port:

```sh
sudo systemctl stop hue-button
arduino-cli compile --fqbn arduino:avr:uno arduino/button
arduino-cli upload -p /dev/ttyACM0 --fqbn arduino:avr:uno arduino/button
sudo systemctl start hue-button
```
