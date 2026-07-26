#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=0
PREFIX="${HOME}/.local"

usage() {
    cat <<'EOF'
Usage: scripts/install-user.sh [--dry-run] [--prefix PATH]

Installs ByeByeDPI Linux for the current user. No root privileges are used.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --prefix) [ "$#" -ge 2 ] || { echo "Error: --prefix requires a path" >&2; exit 2; }; PREFIX="$2"; shift 2 ;;
        --prefix=*) PREFIX="${1#*=}"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Error: unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SOURCE_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$PREFIX/share/byebyedpi-linux"
BIN_DIR="$PREFIX/bin"
LAUNCHER="$BIN_DIR/byebyedpi-linux"
DESKTOP_DIR="$PREFIX/share/applications"
DESKTOP_FILE="$DESKTOP_DIR/byebyedpi.desktop"
ICON_DIR="$PREFIX/share/icons/hicolor/128x128/apps"
ICON_FILE="$ICON_DIR/byebyedpi.png"

required_files=(
    "$SOURCE_DIR/src/main.py"
    "$SOURCE_DIR/pyproject.toml"
    "$SOURCE_DIR/requirements-runtime.txt"
    "$SOURCE_DIR/data/icon.png"
    "$SOURCE_DIR/vendor/byedpi/Makefile"
)
for path in "${required_files[@]}"; do
    if [ ! -f "$path" ]; then
        echo "Error: project checkout is incomplete; missing $path" >&2
        echo "Clone with: git clone --recurse-submodules <repository-url>" >&2
        exit 1
    fi
done

if [ "$PREFIX" = "/" ] || [ -z "$PREFIX" ]; then
    echo "Error: unsafe installation prefix" >&2
    exit 2
fi

if [ "$DRY_RUN" -eq 1 ]; then
    cat <<EOF
[DRY-RUN] Source: $SOURCE_DIR
[DRY-RUN] Prefix: $PREFIX
[DRY-RUN] Validate Python >= 3.10 and venv support
[DRY-RUN] Build vendor/byedpi/ciadpi with make when missing
[DRY-RUN] Copy application to $APP_DIR (excluding .git, .venv, caches and test artifacts)
[DRY-RUN] Create venv and install requirements-runtime.txt (uv acceleration if available)
[DRY-RUN] Create launcher: $LAUNCHER
[DRY-RUN] Create desktop file: $DESKTOP_FILE
[DRY-RUN] Install icon: $ICON_FILE
EOF
    exit 0
fi

command -v python3 >/dev/null 2>&1 || { echo "Error: python3 is required" >&2; exit 1; }
python3 - <<'PY' || { echo "Error: Python 3.10 or newer is required" >&2; exit 1; }
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
python3 -m venv --help >/dev/null 2>&1 || { echo "Error: Python venv support is required" >&2; exit 1; }

CIADPI="$SOURCE_DIR/vendor/byedpi/ciadpi"
if [ ! -x "$CIADPI" ]; then
    command -v make >/dev/null 2>&1 || { echo "Error: make is required to build ciadpi" >&2; exit 1; }
    CC_BIN="$(command -v cc || command -v gcc || command -v clang || true)"
    [ -n "$CC_BIN" ] || { echo "Error: a C compiler (cc, gcc or clang) is required" >&2; exit 1; }
    echo "Building ciadpi..."
    make -C "$SOURCE_DIR/vendor/byedpi" CC="$CC_BIN"
fi
[ -x "$CIADPI" ] || { echo "Error: ciadpi build did not produce an executable" >&2; exit 1; }

mkdir -p "$PREFIX/share" "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR"
rm -rf "$APP_DIR.tmp"
mkdir -p "$APP_DIR.tmp"
SOURCE_DIR="$SOURCE_DIR" DEST_DIR="$APP_DIR.tmp" python3 - <<'PY'
import os
import shutil
from pathlib import Path
source = Path(os.environ["SOURCE_DIR"])
dest = Path(os.environ["DEST_DIR"])
ignored_names = {
    ".git", ".github", ".venv", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "tests",
}
for item in source.iterdir():
    if item.name in ignored_names:
        continue
    target = dest / item.name
    if item.is_dir():
        shutil.copytree(
            item,
            target,
            ignore=shutil.ignore_patterns(
                ".git", "__pycache__", "*.pyc", "*.pyo", ".pytest_cache"
            ),
        )
    else:
        shutil.copy2(item, target)
PY
rm -rf "$APP_DIR"
mv "$APP_DIR.tmp" "$APP_DIR"

python3 -m venv "$APP_DIR/.venv"
if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$APP_DIR/.venv/bin/python" -r "$APP_DIR/requirements-runtime.txt"
else
    "$APP_DIR/.venv/bin/python" -m pip install --disable-pip-version-check -r "$APP_DIR/requirements-runtime.txt"
fi

cat > "$LAUNCHER" <<EOF
#!/bin/sh
exec "$APP_DIR/.venv/bin/python" "$APP_DIR/src/main.py" "\$@"
EOF
chmod 0755 "$LAUNCHER"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=ByeByeDPI Linux
Comment=Local ByeDPI SOCKS5 client and strategy tester
Exec=$LAUNCHER
TryExec=$LAUNCHER
Icon=byebyedpi
Terminal=false
Categories=Network;
StartupNotify=true
Keywords=proxy;SOCKS5;DPI;network;
EOF
install -m 0644 "$SOURCE_DIR/data/icon.png" "$ICON_FILE"

if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$DESKTOP_FILE"
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi

echo "ByeByeDPI Linux installed successfully."
echo "Launcher: $LAUNCHER"
