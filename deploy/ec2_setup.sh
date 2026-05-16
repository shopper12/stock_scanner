#!/usr/bin/env bash
set -euo pipefail
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv git
cd /opt
if [ ! -d stock_scanner ]; then
  sudo git clone https://github.com/shopper12/stock_scanner.git stock_scanner
fi
sudo chown -R "$USER":"$USER" /opt/stock_scanner
cd /opt/stock_scanner
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp -n .env.example .env || true
echo 'Edit /opt/stock_scanner/.env before enabling systemd service.'
