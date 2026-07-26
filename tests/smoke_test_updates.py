#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication

from strategies_dialog import StrategiesDialog
from update_dialog import UpdateDialog
from update_manager import UpdateManager


def main() -> int:
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        data_dir = root / "data"
        data_dir.mkdir()
        for name in ("strategies.json", "test_targets.json"):
            shutil.copy2(ROOT / "data" / name, data_dir / name)

        assets = root / "upstream" / "app" / "src" / "main" / "assets"
        assets.mkdir(parents=True)
        (assets / "proxytest_strategies.list").write_text("--split 123\n", encoding="utf-8")

        manager = UpdateManager(data_dir, backup_dir=root / "backups")
        preview = manager.preview_local("strategies", root / "upstream", commit="smoke")
        dialog = UpdateDialog(data_dir, manager=manager)
        dialog.current_preview = preview
        dialog.apply_btn.setEnabled(True)
        dialog.apply_preview()
        assert manager.list_backups("strategies")
        dialog.rollback_backup()
        dialog.close()

        library = StrategiesDialog()
        assert library.btn_updates.text().startswith("Updates")
        library.close()
        app.processEvents()

    print("Update center smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
