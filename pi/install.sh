#!/bin/sh
# Install the hue-button systemd service for the current user, running from this checkout.
set -e
DIR=$(cd "$(dirname "$0")" && pwd)
USER_NAME=$(id -un)
ENV_FILE="${HUE_ENV:-$HOME/.hue.env}"

[ -f "$ENV_FILE" ] || { echo "$ENV_FILE not found: run python3 $DIR/pair.py first"; exit 1; }
python3 -c "import serial" 2>/dev/null || sudo apt-get install -y python3-serial
# The Uno shows up as /dev/ttyACM0, which belongs to the dialout group.
id -nG "$USER_NAME" | grep -qw dialout || { sudo usermod -aG dialout "$USER_NAME"; echo "added $USER_NAME to dialout"; }

sudo tee /etc/systemd/system/hue-button.service >/dev/null <<UNIT
[Unit]
Description=Hue light toggle button and dimmer (Arduino Uno)
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
Environment=HUE_ENV=$ENV_FILE
ExecStart=/usr/bin/python3 $DIR/hue_button.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable hue-button >/dev/null 2>&1
sudo systemctl restart hue-button
echo "installed: follow logs with  journalctl -u hue-button -f"
