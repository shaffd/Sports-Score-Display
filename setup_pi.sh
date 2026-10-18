#!/usr/bin/env bash
set -euo pipefail

echo "=== Sports Score Display Pi Setup ==="

echo "Updating system packages..."
sudo apt-get update

echo "Installing Python and HZeller build dependencies..."
sudo apt-get install -y \
  build-essential \
  cmake \
  cython3 \
  fonts-dejavu-core \
  git \
  python-dev-is-python3 \
  python3-dev \
  python3-pil \
  python3-venv \
  network-manager

echo "Creating Python virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

echo "Installing application dependencies..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "Installing HZeller's current Python bindings..."
python -m pip install "git+https://github.com/hzeller/rpi-rgb-led-matrix"

echo "Installing the GameBlink Wi-Fi setup service..."
sudo install -d -m 0755 /usr/local/lib/gameblink
sudo install -m 0755 wifi_setup.py /usr/local/lib/gameblink/wifi_setup.py
sudo install -m 0644 deploy/systemd/gameblink-wifi.service \
  /etc/systemd/system/gameblink-wifi.service
sudo systemctl daemon-reload
sudo systemctl enable --now gameblink-wifi.service

echo "Setup complete."
echo "1. Edit config.json for your panel and wiring."
echo "2. Change output to matrix, or pass --output matrix."
echo "3. Run: sudo .venv/bin/python main.py --output matrix"
echo "4. If no saved Wi-Fi connects within 30 seconds, join the displayed"
echo "   GameBlink-XXXX network with password: GAMEBLINK"
echo "5. Open http://10.42.0.1 if the setup page does not appear automatically."
