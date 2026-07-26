#!/usr/bin/env bash
set -e

DRY_RUN=0
PREFIX="$HOME/.local"

for arg in "$@"; do
    case $arg in
        --dry-run)
            DRY_RUN=1
            ;;
        --prefix=*)
            PREFIX="${arg#*=}"
            ;;
    esac
done

APP_DIR="$PREFIX/share/byebyedpi-linux"
APP_DESKTOP="$PREFIX/share/applications/byebyedpi.desktop"
ICON_FILE="$PREFIX/share/icons/hicolor/128x128/apps/byebyedpi.png"

echo "Uninstalling ByeByeDPI-Linux from $PREFIX..."

if [ "$DRY_RUN" -eq 1 ]; then
    echo "[DRY-RUN] Would recover GNOME proxy journal if exists."
    echo "[DRY-RUN] Would remove $APP_DIR"
    echo "[DRY-RUN] Would remove $APP_DESKTOP"
    echo "[DRY-RUN] Would remove $ICON_FILE"
    exit 0
fi

# Try recovery
if [ -d "$APP_DIR" ] && [ -f "$APP_DIR/.venv/bin/python3" ]; then
    echo "Attempting proxy recovery before uninstall..."
    # A simple recovery call
    "$APP_DIR/.venv/bin/python3" -c "
import sys, os
sys.path.insert(0, os.path.join('$APP_DIR', 'src'))
try:
    from gnome_proxy import GnomeProxyAdapter
    adapter = GnomeProxyAdapter()
    adapter.restore_proxy()
except Exception as e:
    print('Recovery failed or not needed:', e)
" || true
fi

rm -rf "$APP_DIR"
rm -f "$APP_DESKTOP"
rm -f "$ICON_FILE"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$PREFIX/share/applications" || true
fi

echo "Uninstallation complete."
