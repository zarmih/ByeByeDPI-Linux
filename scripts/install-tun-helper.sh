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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
HELPER_SRC="$SCRIPT_DIR/../packaging/tun-helper/byebyedpi-tun-helper"
POLICY_SRC="$SCRIPT_DIR/../packaging/tun-helper/org.byebyedpi.linux.tun.policy"
DEST_DIR="/usr/libexec/byebyedpi-linux"
DEST_FILE="$DEST_DIR/tun-helper"
POLICY_DEST="/usr/share/polkit-1/actions/org.byebyedpi.linux.tun.policy"

if [ -h "$HELPER_SRC" ] || [ -h "$POLICY_SRC" ]; then
    echo "Error: Source files must not be symlinks." >&2
    exit 1
fi

if [ "$DRY_RUN" -eq 1 ]; then
    echo "[DRY-RUN] Would create directory $DEST_DIR (mode 0755 root:root)"
    echo "[DRY-RUN] Would install $HELPER_SRC to $DEST_FILE (mode 0700 root:root)"
    echo "[DRY-RUN] Would install $POLICY_SRC to $POLICY_DEST (mode 0644 root:root)"
    exit 0
fi

echo "Installing ByeByeDPI TUN Helper..."

install -d -m 0755 -o root -g root "$DEST_DIR"
install -m 0700 -o root -g root "$HELPER_SRC" "$DEST_FILE"

if [ -d "/usr/share/polkit-1/actions" ]; then
    install -m 0644 -o root -g root "$POLICY_SRC" "$POLICY_DEST"
else
    echo "Warning: /usr/share/polkit-1/actions not found. Polkit policy not installed."
fi

echo "TUN Helper successfully installed to $DEST_FILE"
