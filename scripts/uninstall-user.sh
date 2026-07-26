#!/usr/bin/env bash
set -e

echo "Uninstalling ByeByeDPI-Linux..."
APP_DIR="$HOME/.local/share/byebyedpi-linux"
APP_DESKTOP="$HOME/.local/share/applications/byebyedpi.desktop"
ICON_FILE="$HOME/.local/share/icons/hicolor/128x128/apps/byebyedpi.png"

rm -rf "$APP_DIR"
rm -f "$APP_DESKTOP"
rm -f "$ICON_FILE"

# Update desktop database
update-desktop-database "$HOME/.local/share/applications" || true

echo "Uninstallation complete."
