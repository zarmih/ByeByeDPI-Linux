#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_smoke_root = tempfile.TemporaryDirectory(prefix="byebyedpi-updater-smoke-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_smoke_root.name) / "config")
os.environ["XDG_DATA_HOME"] = str(Path(_smoke_root.name) / "data")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication
import app_update_dialog


class FakeCheckThread(QThread):
    result = Signal(object)
    error = Signal(str)

    def start(self) -> None:
        self.result.emit(None)


def main() -> int:
    app_update_dialog.CheckUpdateThread = FakeCheckThread
    app = QApplication.instance() or QApplication([])
    dialog = app_update_dialog.AppUpdateDialog()
    dialog.show()
    app.processEvents()
    assert "up to date" in dialog.status_label.text().lower()
    assert not dialog.download_btn.isVisible()
    dialog.close()
    app.processEvents()
    print("App updater GUI smoke test passed.")
    _smoke_root.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
