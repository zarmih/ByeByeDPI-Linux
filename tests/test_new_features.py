from __future__ import annotations

import json
import os
import struct
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from diagnostics import DiagnosticsDialog
from gnome_proxy import GnomeProxyAdapter, PROXY_KEYS
from main import MainWindow
from strategies_dialog import StrategiesDialog
from strategy_tester import StrategyTesterThread


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


class FakeGSettingsRunner:
    def __init__(self):
        self.values = {
            schema: {
                key: (
                    "'none'" if key == "mode"
                    else "false" if key == "use-same-proxy"
                    else "[]" if key == "ignore-hosts"
                    else "''" if key in {"host", "autoconfig-url"}
                    else "0"
                )
                for key in keys
            }
            for schema, keys in PROXY_KEYS.items()
        }
        self.calls: list[list[str]] = []
        self.fail_on: tuple[str, str] | None = None

    def __call__(self, argv, **kwargs):
        assert isinstance(argv, list)
        assert kwargs.get("timeout") == 3
        self.calls.append(list(argv))
        operation = argv[1]
        if operation == "list-schemas":
            return subprocess.CompletedProcess(argv, 0, "\n".join(self.values), "")
        if operation == "list-keys":
            return subprocess.CompletedProcess(argv, 0, "\n".join(self.values[argv[2]]), "")
        if operation == "get":
            return subprocess.CompletedProcess(
                argv, 0, self.values[argv[2]][argv[3]] + "\n", ""
            )
        if operation == "set":
            if self.fail_on == (argv[2], argv[3]):
                return subprocess.CompletedProcess(argv, 1, "", "simulated failure")
            self.values[argv[2]][argv[3]] = argv[4]
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise AssertionError(argv)


def make_adapter(tmp_path: Path, runner: FakeGSettingsRunner) -> GnomeProxyAdapter:
    return GnomeProxyAdapter(
        runner=runner,
        data_dir=tmp_path,
        gsettings_path="gsettings",
    )


def test_gnome_proxy_uses_socks_and_restores_full_snapshot(tmp_path):
    runner = FakeGSettingsRunner()
    original = json.loads(json.dumps(runner.values))
    adapter = make_adapter(tmp_path, runner)

    assert adapter.apply_proxy(1080), adapter.last_error
    assert runner.values["org.gnome.system.proxy.socks"]["host"] == "'127.0.0.1'"
    assert runner.values["org.gnome.system.proxy.socks"]["port"] == "1080"
    assert runner.values["org.gnome.system.proxy.http"]["host"] == "''"
    assert runner.values["org.gnome.system.proxy.https"]["host"] == "''"
    assert runner.values["org.gnome.system.proxy"]["mode"] == "'manual'"

    payload = json.loads(Path(adapter.journal_file).read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["state"] == "applied"
    assert payload["settings"] == original
    assert payload["applied"] == {"host": "127.0.0.1", "port": 1080}

    assert adapter.restore_proxy(), adapter.last_error
    assert runner.values == original
    assert not Path(adapter.journal_file).exists()


def test_repeated_apply_does_not_overwrite_original_snapshot(tmp_path):
    runner = FakeGSettingsRunner()
    adapter = make_adapter(tmp_path, runner)
    assert adapter.apply_proxy(1080)
    original_journal = Path(adapter.journal_file).read_bytes()
    assert not adapter.apply_proxy(1081)
    assert "recovery" in adapter.last_error.lower()
    assert Path(adapter.journal_file).read_bytes() == original_journal


def test_partial_restore_retains_journal(tmp_path):
    runner = FakeGSettingsRunner()
    adapter = make_adapter(tmp_path, runner)
    assert adapter.apply_proxy(1080)
    runner.fail_on = ("org.gnome.system.proxy.socks", "host")
    assert not adapter.restore_proxy()
    assert Path(adapter.journal_file).exists()
    assert "simulated failure" in adapter.last_error


def test_invalid_journal_is_rejected_without_deletion(tmp_path):
    runner = FakeGSettingsRunner()
    adapter = make_adapter(tmp_path, runner)
    journal = Path(adapter.journal_file)
    journal.write_text('{"version": 999}', encoding="utf-8")
    assert not adapter.restore_proxy()
    assert journal.exists()
    assert "Unsupported" in adapter.last_error


def test_no_real_gsettings_set_is_used_in_adapter_tests(tmp_path):
    runner = FakeGSettingsRunner()
    adapter = make_adapter(tmp_path, runner)
    assert adapter.apply_proxy(1080)
    set_calls = [call for call in runner.calls if call[1] == "set"]
    assert set_calls
    assert all(call[0] == "gsettings" for call in set_calls)
    assert not any(call[2].endswith(".http") and call[4] == "'127.0.0.1'" for call in set_calls)


def test_strategy_tester_timeout_configuration():
    tester = StrategyTesterThread([], [], connect_timeout=7, total_timeout=18)
    assert tester.connect_timeout == 7
    assert tester.total_timeout == 18
    tester = StrategyTesterThread([], [], connect_timeout=30, total_timeout=2)
    assert tester.total_timeout == 30


def test_strategy_dialog_persistence(qapp, tmp_path, monkeypatch):
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    settings = QSettings("ByeByeDPI", "ByeByeDPI-Linux")
    settings.clear()
    settings.setValue("strategies/selected_target_ids", ["youtube_0", "telegram_0"])
    settings.setValue("strategies/connect_timeout", 8)
    settings.setValue("strategies/total_timeout", 22)
    settings.sync()

    dialog = StrategiesDialog()
    selected = {target["target_id"] for target in dialog.get_selected_targets()}
    assert {"youtube_0", "telegram_0"}.issubset(selected)
    assert dialog.connect_timeout_spin.value() == 8
    assert dialog.total_timeout_spin.value() == 22
    dialog.connect_timeout_spin.setValue(9)
    dialog.total_timeout_spin.setValue(24)
    dialog.save_dialog_settings()
    dialog.close()

    reloaded = StrategiesDialog()
    assert reloaded.connect_timeout_spin.value() == 9
    assert reloaded.total_timeout_spin.value() == 24
    reloaded.close()
    settings.clear()


def test_main_rejects_secret_arguments():
    assert MainWindow._args_are_safe_to_store("--split 1 --tlsrec 1+s")
    assert not MainWindow._args_are_safe_to_store("--token=secret-value")
    assert not MainWindow._args_are_safe_to_store("--password=hunter2")


def test_close_without_tray_cleans_process_and_proxy(qapp, monkeypatch):
    monkeypatch.setattr(MainWindow, "_recover_pending_proxy", lambda self: None)
    window = MainWindow()
    window.tray_available = False
    window.pm = MagicMock()
    window.gnome_proxy = MagicMock()
    window.gnome_proxy.has_journal.return_value = True
    window.gnome_proxy.restore_proxy.return_value = True
    event = MagicMock()
    window.closeEvent(event)
    window.pm.stop.assert_called_once()
    window.gnome_proxy.restore_proxy.assert_called_once()
    event.accept.assert_called_once()


def test_diagnostics_report_is_copyable_and_redacts_home(qapp, monkeypatch, tmp_path):
    binary = tmp_path / "vendor" / "byedpi" / "ciadpi"
    binary.parent.mkdir(parents=True)
    (binary.parent / "Makefile").write_text("all:\n", encoding="utf-8")
    binary.write_bytes(b"binary")
    binary.chmod(0o755)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "icon.png").write_bytes(b"x" * 512)
    (tmp_path / "data" / "byebyedpi.desktop").write_text("[Desktop Entry]\nType=Application\nName=X\nExec=x\n", encoding="utf-8")

    tools = {
        "curl": "/usr/bin/curl",
        "git": "/usr/bin/git",
        "make": "/usr/bin/make",
        "cc": "/usr/bin/cc",
    }
    monkeypatch.setattr("diagnostics_core.shutil.which", lambda name: tools.get(name))
    dialog = DiagnosticsDialog(str(binary))
    dialog.run_diagnostics()

    import time
    for _ in range(50):
        if dialog.last_report is not None:
            break
        qapp.processEvents()
        time.sleep(0.01)

    report = dialog.report_area.toPlainText()
    assert "PySide6" in report
    assert str(Path.home()) not in report


def test_installer_and_uninstaller_dry_run(tmp_path):
    prefix = tmp_path / "prefix"
    install = subprocess.run(
        ["bash", "scripts/install-user.sh", "--dry-run", "--prefix", str(prefix)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert install.returncode == 0, install.stderr
    assert "Build vendor/byedpi/ciadpi" in install.stdout
    assert not prefix.exists()

    uninstall = subprocess.run(
        ["bash", "scripts/uninstall-user.sh", "--dry-run", "--prefix", str(prefix)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert uninstall.returncode == 0, uninstall.stderr
    assert not prefix.exists()


def test_desktop_template_and_icon_are_real_assets():
    desktop = Path("data/byebyedpi.desktop").read_text(encoding="utf-8")
    assert "sh -c" not in desktop
    assert "Exec=byebyedpi-linux" in desktop
    assert "TryExec=byebyedpi-linux" in desktop

    png = Path("data/icon.png").read_bytes()
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (128, 128)
    assert len(png) >= 256


def test_runtime_requirements_do_not_include_test_dependencies():
    requirements = Path("requirements-runtime.txt").read_text(encoding="utf-8").lower()
    assert "pyside6" in requirements
    assert "pytest" not in requirements
    assert "psutil" not in requirements
