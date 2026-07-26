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
BIN_DIR="$PREFIX/bin"
APP_DESKTOP="$PREFIX/share/applications/byebyedpi.desktop"
ICON_DIR="$PREFIX/share/icons/hicolor/128x128/apps"
ICON_FILE="$ICON_DIR/byebyedpi.png"

echo "Installing ByeByeDPI-Linux to $PREFIX..."

if [ "$DRY_RUN" -eq 1 ]; then
    echo "[DRY-RUN] Would create directories: $APP_DIR, $BIN_DIR, $ICON_DIR, $(dirname "$APP_DESKTOP")"
    echo "[DRY-RUN] Would copy files to $APP_DIR"
    echo "[DRY-RUN] Would setup venv and install dependencies: PySide6 psutil"
    echo "[DRY-RUN] Would copy desktop file to $APP_DESKTOP"
    echo "[DRY-RUN] Would copy icon to $ICON_FILE"
    exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is required but not found."
    exit 1
fi

if ! python3 -m venv --help >/dev/null 2>&1; then
    echo "Error: python3-venv is required but not found."
    exit 1
fi

if [ ! -f "vendor/byedpi/ciadpi" ]; then
    echo "ciadpi not found. Attempting to build..."
    if command -v make >/dev/null 2>&1 && command -v gcc >/dev/null 2>&1; then
        git submodule update --init --recursive || true
        make -C vendor/byedpi || { echo "Failed to build ciadpi"; exit 1; }
    else
        echo "Error: ciadpi binary missing and build tools (make, gcc) not found."
        exit 1
    fi
fi

mkdir -p "$APP_DIR" "$BIN_DIR" "$ICON_DIR" "$(dirname "$APP_DESKTOP")"

rsync -a --exclude='.git' --exclude='.venv' --exclude='__pycache__' ./ "$APP_DIR/"

echo "Setting up virtual environment..."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install PySide6 psutil

# Ensure a valid icon exists
if [ ! -s "data/icon.png" ]; then
    python3 -c 'import base64; open("data/icon.png", "wb").write(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="))'
fi

# Generate desktop file
cat > "$APP_DESKTOP" <<EOF
[Desktop Entry]
Name=ByeByeDPI-Linux
Comment=DPI Bypass Client
Exec=sh -c "cd '$APP_DIR' && source .venv/bin/activate && python3 src/main.py"
Icon=byebyedpi
Terminal=false
Type=Application
Categories=Network;Utility;
EOF

if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$APP_DESKTOP" || echo "Warning: desktop-file-validate failed."
fi

cp data/icon.png "$ICON_FILE" 2>/dev/null || true

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$PREFIX/share/applications" || true
fi

echo "Installation complete."
