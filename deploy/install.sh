#!/usr/bin/env bash
# Instalación en la VM de Oracle (Ubuntu 24.04, ARM). Ejecutar desde la carpeta del proyecto:
#   bash deploy/install.sh
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

echo "==> Paquetes del sistema"
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip sqlite3 unzip
sudo timedatectl set-timezone Europe/Madrid || true

echo "==> Entorno virtual de Python"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "==> Chromium para Playwright (Deymar y KW Kinver)"
.venv/bin/playwright install --with-deps chromium || \
  echo "AVISO: no se pudo instalar Chromium. Deymar y KW Kinver se saltarán; el resto funciona."

mkdir -p data backups
[ -f .env ] || { cp .env.example .env; echo "==> Rellena el archivo .env (token y chat id)"; }
chmod 600 .env
chmod +x deploy/backup.sh

echo "==> Servicio systemd"
sed "s#/home/ubuntu/granada-monitor#$APP_DIR#g; s#User=ubuntu#User=$USER#" \
  deploy/granada-monitor.service | sudo tee /etc/systemd/system/granada-monitor.service >/dev/null
sudo systemctl daemon-reload
echo
echo "Listo. Siguientes pasos:"
echo "  1) nano .env                      (pega token y chat id)"
echo "  2) .venv/bin/python -m monitor check"
echo "  3) .venv/bin/python -m monitor telegram-test"
echo "  4) sudo systemctl enable --now granada-monitor"
