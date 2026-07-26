#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from update_dialog import UpdateDialog


def main() -> int:
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("Real display update smoke skipped: no display.")
        return 0
    app = QApplication.instance() or QApplication([])
    dialog = UpdateDialog(ROOT / "data")
    dialog.show()
    QTimer.singleShot(1500, dialog.close)
    QTimer.singleShot(2000, app.quit)
    app.exec()
    print("Real display update window opened and closed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
