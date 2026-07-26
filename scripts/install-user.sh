#!/usr/bin/env bash
set -e

echo "Installing ByeByeDPI-Linux to ~/.local..."
APP_DIR="$HOME/.local/share/byebyedpi-linux"
BIN_DIR="$HOME/.local/bin"
APP_DESKTOP="$HOME/.local/share/applications/byebyedpi.desktop"
ICON_DIR="$HOME/.local/share/icons/hicolor/128x128/apps"

mkdir -p "$APP_DIR" "$BIN_DIR" "$ICON_DIR" "$(dirname "$APP_DESKTOP")"

# We do not copy .venv or .git.
rsync -av --exclude='.git' --exclude='.venv' --exclude='__pycache__' ./ "$APP_DIR/"

echo "Setting up virtual environment in $APP_DIR..."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/pyproject.toml" || "$APP_DIR/.venv/bin/pip" install PySide6 pytest psutil 

cp data/byebyedpi.desktop "$APP_DESKTOP"
cp data/icon.png "$ICON_DIR/byebyedpi.png" 2>/dev/null || true

# Update desktop database
update-desktop-database "$HOME/.local/share/applications" || true

echo "Installation complete. You can launch ByeByeDPI-Linux from your application menu."
