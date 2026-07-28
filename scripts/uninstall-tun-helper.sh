#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=1
fi

if [ "$EUID" -ne 0 ] && [ "$DRY_RUN" -eq 0 ]; then
    echo "Error: This script must be run as root (EUID=0)." >&2
    exit 1
fi

DEST_DIR="/usr/libexec/byebyedpi-linux"
DEST_FILE="$DEST_DIR/tun-helper"
POLICY_DEST="/usr/share/polkit-1/actions/org.byebyedpi.linux.tun.policy"

if [ "$DRY_RUN" -eq 1 ]; then
    echo "[DRY-RUN] Would run tun-helper recover if it exists"
    echo "[DRY-RUN] Would check lstat permissions of $DEST_FILE and $POLICY_DEST"
    echo "[DRY-RUN] Would remove $DEST_FILE"
    echo "[DRY-RUN] Would remove directory $DEST_DIR if empty"
    echo "[DRY-RUN] Would remove $POLICY_DEST"
    exit 0
fi

echo "Uninstalling ByeByeDPI TUN Helper..."

if [ -x "$DEST_FILE" ]; then
    echo "Running TUN Helper recovery before removal..."
    "$DEST_FILE" recover
fi

if [ -e "$DEST_FILE" ] || [ -h "$DEST_FILE" ]; then
    if [ ! -f "$DEST_FILE" ] || [ -h "$DEST_FILE" ]; then
        echo "Error: $DEST_FILE is not a regular file or is a symlink. Aborting." >&2
        exit 1
    fi
    owner=$(stat -c '%u' "$DEST_FILE")
    perms=$(stat -c '%a' "$DEST_FILE")
    if [ "$owner" != "0" ] || [[ "$perms" =~ [2367]$ ]]; then
        echo "Error: $DEST_FILE has unsafe permissions/ownership. Aborting." >&2
        exit 1
    fi
    rm -f -- "$DEST_FILE"
fi

if [ -d "$DEST_DIR" ]; then
    rmdir --ignore-fail-on-non-empty "$DEST_DIR" 2>/dev/null || true
fi

if [ -e "$POLICY_DEST" ] || [ -h "$POLICY_DEST" ]; then
    if [ ! -f "$POLICY_DEST" ] || [ -h "$POLICY_DEST" ]; then
        echo "Error: $POLICY_DEST is not a regular file or is a symlink. Aborting." >&2
        exit 1
    fi
    rm -f -- "$POLICY_DEST"
fi

echo "TUN Helper successfully uninstalled."
