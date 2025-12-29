#!/bin/bash

echo "=== Sports Score Display Pi Setup ==="

echo "Updating system packages..."
sudo apt update -y

echo "Installing required system packages..."
sudo apt install -y python3 python3-venv git

echo "Creating Python virtual environment..."
python3 -m venv venv

echo "Activating virtual environment..."
source venv/bin/activate

echo "Upgrading pip inside virtual environment..."
pip install --upgrade pip

echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Setup complete!"
echo "To activate the environment in the future, run:"
echo "source venv/bin/activate"