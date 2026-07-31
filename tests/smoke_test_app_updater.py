#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_smoke_root = tempfile.TemporaryDirectory(prefix="byebyedpi-updater-smoke-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_smoke_root.name) / "config")
os.environ["XDG_DATA_HOME"] = str(Path(_smoke_root.name) / "data")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QCloseEvent
import app_update_dialog


class FakeCheckThread(QThread):
    result = Signal(object)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self._is_running = True

    def start(self) -> None:
        self._is_running = True

    def isRunning(self) -> bool:
        return self._is_running

    def finish_mock(self):
        self._is_running = False
        self.result.emit(None)
        self.finished.emit()


def main() -> int:
    app_update_dialog.CheckUpdateThread = FakeCheckThread
    app = QApplication.instance() or QApplication([])
    dialog = app_update_dialog.AppUpdateDialog()
    dialog.show()
    app.processEvents()

    # Model running checker and check that close is ignored
    assert dialog.checker.isRunning()

    close_event = QCloseEvent()
    dialog.closeEvent(close_event)
    assert not close_event.isAccepted()

    # Finish checker
    dialog.checker.finish_mock()
    app.processEvents()

    assert "up to date" in dialog.status_label.text().lower()
    assert not dialog.download_btn.isVisible()

    # Close again, should be accepted
    close_event2 = QCloseEvent()
    dialog.closeEvent(close_event2)
    assert close_event2.isAccepted()
    dialog.close()
    app.processEvents()

    print("App updater GUI smoke test passed.")
    _smoke_root.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
