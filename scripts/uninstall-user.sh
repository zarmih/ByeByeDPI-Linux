#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=0
PURGE_DATA=0
PREFIX="${HOME}/.local"

usage() {
    cat <<'EOF'
Usage: scripts/uninstall-user.sh [--dry-run] [--prefix PATH] [--purge-data]

Removes only files installed by ByeByeDPI Linux. User history and settings are
kept unless --purge-data is specified. GNOME proxy recovery is attempted first.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --purge-data) PURGE_DATA=1; shift ;;
        --prefix) [ "$#" -ge 2 ] || { echo "Error: --prefix requires a path" >&2; exit 2; }; PREFIX="$2"; shift 2 ;;
        --prefix=*) PREFIX="${1#*=}"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Error: unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [ "$PREFIX" = "/" ] || [ -z "$PREFIX" ]; then
    echo "Error: unsafe uninstall prefix" >&2
    exit 2
fi

APP_DIR="$PREFIX/share/byebyedpi-linux"
LAUNCHER="$PREFIX/bin/byebyedpi-linux"
DESKTOP_FILE="$PREFIX/share/applications/byebyedpi.desktop"
ICON_FILE="$PREFIX/share/icons/hicolor/128x128/apps/byebyedpi.png"
XDG_DATA_ROOT="${XDG_DATA_HOME:-${HOME}/.local/share}"
USER_DATA_DIR="$XDG_DATA_ROOT/ByeByeDPI-Linux"
LEGACY_DATA_DIR_1="$XDG_DATA_ROOT/ByeByeDPI/ByeByeDPI-Linux"
LEGACY_DATA_DIR_2="$XDG_DATA_ROOT/ByeByeDPI/ByeByeDPI-Linux/ByeByeDPI-Linux"
LEGACY_DATA_DIR_3="$XDG_DATA_ROOT/ByeByeDPI-Linux/ByeByeDPI-Linux"

if [ "$DRY_RUN" -eq 1 ]; then
    echo "[DRY-RUN] Would recover a pending GNOME proxy journal using $APP_DIR"
    echo "[DRY-RUN] Would remove $APP_DIR"
    echo "[DRY-RUN] Would remove $LAUNCHER"
    echo "[DRY-RUN] Would remove $DESKTOP_FILE"
    echo "[DRY-RUN] Would remove $ICON_FILE"
    if [ "$PURGE_DATA" -eq 1 ]; then
        echo "[DRY-RUN] Would purge known ByeByeDPI data paths under $XDG_DATA_ROOT"
    fi
    exit 0
fi

DATA_PATHS=(
    "$USER_DATA_DIR"
    "$LEGACY_DATA_DIR_1"
    "$LEGACY_DATA_DIR_2"
    "$LEGACY_DATA_DIR_3"
)

JOURNALS_FOUND=0
for dp in "${DATA_PATHS[@]}"; do
    if [ -f "$dp/gnome_proxy_journal.json" ]; then
        JOURNALS_FOUND=$((JOURNALS_FOUND + 1))
    fi
done

if [ "$JOURNALS_FOUND" -gt 1 ]; then
    echo "Error: Multiple GNOME proxy recovery journals found. Automatic recovery is unsafe; uninstall aborted." >&2
    exit 3
elif [ "$JOURNALS_FOUND" -eq 1 ]; then
    if [ ! -x "$APP_DIR/.venv/bin/python" ] || [ ! -f "$APP_DIR/src/gnome_proxy.py" ]; then
        echo "Error: GNOME proxy recovery journal exists but runtime is broken/missing. Uninstall aborted." >&2
        exit 3
    fi
    APP_DIR="$APP_DIR" "$APP_DIR/.venv/bin/python" - <<'PY' || exit 3
import os
import sys
from pathlib import Path
app_dir = Path(os.environ["APP_DIR"])
sys.path.insert(0, str(app_dir / "src"))
try:
    from gnome_proxy import GnomeProxyAdapter
    adapter = GnomeProxyAdapter()
    if adapter.has_journal() and not adapter.restore_proxy():
        print("Error: GNOME proxy recovery failed; uninstall aborted.", file=sys.stderr)
        print(adapter.last_error, file=sys.stderr)
        sys.exit(3)
except Exception as e:
    print(f"Error: GNOME proxy recovery crashed; uninstall aborted. Details: {e}", file=sys.stderr)
    sys.exit(3)
PY
fi

rm -rf -- "$APP_DIR"
rm -f -- "$LAUNCHER" "$DESKTOP_FILE" "$ICON_FILE"

if [ "$PURGE_DATA" -eq 1 ]; then
    DATA_PATHS=(
        "$USER_DATA_DIR"
        "$LEGACY_DATA_DIR_1"
        "$LEGACY_DATA_DIR_2"
        "$LEGACY_DATA_DIR_3"
    )
    for data_path in "${DATA_PATHS[@]}"; do
        safe_path=0
        for allowed_path in "${DATA_PATHS[@]}"; do
            if [ "$data_path" = "$allowed_path" ]; then
                safe_path=1
                break
            fi
        done
        if [ "$safe_path" -ne 1 ]; then
            echo "Error: refusing unsafe data path: $data_path" >&2
            exit 2
        fi
        rm -rf -- "$data_path"
    done
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$PREFIX/share/applications" >/dev/null 2>&1 || true
fi

for directory in \
    "$PREFIX/share/icons/hicolor/128x128/apps" \
    "$PREFIX/share/applications" \
    "$PREFIX/bin"; do
    rmdir --ignore-fail-on-non-empty "$directory" 2>/dev/null || true
done

echo "ByeByeDPI Linux uninstalled."
echo "Note: System-wide TUN helper (if installed) was not removed."
echo "To remove it, run: sudo scripts/uninstall-tun-helper.sh"
