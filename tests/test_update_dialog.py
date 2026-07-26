from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from update_dialog import UpdateDialog
from update_manager import UpdateManager


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def copy_data(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for name in ("strategies.json", "test_targets.json"):
        (data_dir / name).write_bytes((Path("data") / name).read_bytes())
    return data_dir


def upstream_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "upstream"
    assets = root / "app" / "src" / "main" / "assets"
    assets.mkdir(parents=True)
    (assets / "proxytest_strategies.list").write_text("--split 99\n", encoding="utf-8")
    return root


def test_update_dialog_applies_and_rolls_back_without_network(qapp, tmp_path):
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path / "settings"))
    data_dir = copy_data(tmp_path)
    backup_dir = tmp_path / "backups"
    manager = UpdateManager(data_dir, backup_dir=backup_dir)
    preview = manager.preview_local("strategies", upstream_fixture(tmp_path), commit="c" * 40)
    original = (data_dir / "strategies.json").read_bytes()

    dialog = UpdateDialog(data_dir, manager=manager)
    emitted = []
    dialog.data_updated.connect(emitted.append)
    dialog.current_preview = preview
    dialog.apply_btn.setEnabled(True)
    dialog.apply_preview()

    installed = json.loads((data_dir / "strategies.json").read_text(encoding="utf-8"))
    assert installed["strategies"][0]["args"] == "--split 99"
    assert emitted == ["strategies"]
    assert dialog.backup_combo.count() == 1

    dialog.rollback_backup()
    assert (data_dir / "strategies.json").read_bytes() == original
    assert emitted == ["strategies", "strategies"]
    dialog.close()


def test_update_dialog_background_preview(qapp, tmp_path):
    data_dir = copy_data(tmp_path)
    manager = UpdateManager(data_dir, backup_dir=tmp_path / "backups")
    preview = manager.preview_local("strategies", upstream_fixture(tmp_path), commit="d" * 40)

    class FakeManager:
        def preview_remote(self, kind, proxy):
            assert kind == "strategies"
            assert proxy == "http://127.0.0.1:10808"
            return preview

        def list_backups(self, kind=None):
            return []

    dialog = UpdateDialog(data_dir, manager=FakeManager())
    dialog.proxy_input.setText("http://127.0.0.1:10808")
    dialog.start_preview()
    deadline = time.monotonic() + 3
    while dialog.worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert dialog.worker is None
    assert dialog.current_preview is preview
    assert "Commit: " + "d" * 40 in dialog.report_area.toPlainText()
    assert dialog.apply_btn.isEnabled()
    dialog.close()


def test_update_dialog_rejects_credential_proxy(qapp, tmp_path):
    data_dir = copy_data(tmp_path)
    dialog = UpdateDialog(data_dir, manager=UpdateManager(data_dir, backup_dir=tmp_path / "b"))
    dialog.proxy_input.setText("http://user:pass@localhost:8080")
    dialog.start_preview()
    assert dialog.worker is None
    assert "credentials" in dialog.status_label.text()
    dialog.close()
