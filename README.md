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
- `pi/hue-button.service` is the systemd unit

## Setup on the Pi

```sh
sudo apt install python3-serial
cp .env.example ~/.hue.env   # fill in bridge IP, key, client key
mkdir -p ~/hue-button && cp pi/*.py ~/hue-button/
sudo cp pi/hue-button.service /etc/systemd/system/ && sudo systemctl enable --now hue-button

# flash the Uno (stop the service first, since it holds the serial port)
arduino-cli compile --fqbn arduino:avr:uno arduino/button
arduino-cli upload -p /dev/ttyACM0 --fqbn arduino:avr:uno arduino/button
```

Needs an entertainment area in the Hue app (default name "Living room", or set `HUE_AREA`).
