from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

import gnome_proxy
import paths
import result_bundle
import update_manager
from gnome_proxy import GnomeProxyAdapter




@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


class RestoreRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")


def test_user_data_path_is_independent_of_qt_application_name(qapp):
    before = paths.user_data_dir(create=False)
    app = qapp
    app.setOrganizationName("ByeByeDPI")
    app.setApplicationName("ByeByeDPI-Linux")
    after = paths.user_data_dir(create=False)
    assert after == before
    assert after.name == "ByeByeDPI-Linux"


def test_all_storage_components_share_one_data_root(tmp_path, monkeypatch):
    data_root = tmp_path / "xdg-data"
    config_root = tmp_path / "xdg-config"

    def fake_location(location):
        if location == paths.QStandardPaths.GenericDataLocation:
            return str(data_root)
        if location == paths.QStandardPaths.GenericConfigLocation:
            return str(config_root)
        raise AssertionError(location)

    monkeypatch.setattr(paths, "_writable_location", fake_location)
    expected = data_root / "ByeByeDPI-Linux"
    assert paths.user_data_dir() == expected
    assert paths.user_config_dir() == config_root / "ByeByeDPI-Linux"
    assert Path(GnomeProxyAdapter(runner=RestoreRunner(), gsettings_path=None).journal_file).parent == expected
    assert Path(result_bundle.get_history_dir()).parent == expected
    assert update_manager.UpdateManager(tmp_path / "data").backup_dir == expected / "updates" / "backups"


def test_legacy_gnome_journal_is_discovered_and_restored(tmp_path, monkeypatch):
    current = tmp_path / "current"
    legacy = tmp_path / "legacy"
    current.mkdir()
    legacy.mkdir()
    monkeypatch.setattr(gnome_proxy, "user_data_dir", lambda: current)
    monkeypatch.setattr(gnome_proxy, "data_search_dirs", lambda: (current, legacy))

    journal = legacy / "gnome_proxy_journal.json"
    journal.write_text(
        json.dumps(
            {
                "version": 1,
                "state": "applied",
                "created_at": "2026-07-26T00:00:00+00:00",
                "settings": {"org.gnome.system.proxy": {"mode": "'none'"}},
                "applied": {"host": "127.0.0.1", "port": 1080},
            }
        ),
        encoding="utf-8",
    )
    runner = RestoreRunner()
    adapter = GnomeProxyAdapter(
        runner=runner,
        gsettings_path="gsettings",
        available_keys={
            "org.gnome.system.proxy": {"mode"},
            "org.gnome.system.proxy.socks": {"host", "port"},
        },
    )
    assert adapter.has_journal()
    assert adapter.restore_proxy(), adapter.last_error
    assert not journal.exists()
    assert ["gsettings", "set", "org.gnome.system.proxy", "mode", "'none'"] in runner.calls


def test_multiple_gnome_journals_are_not_ambiguously_restored(tmp_path, monkeypatch):
    current = tmp_path / "current"
    legacy = tmp_path / "legacy"
    current.mkdir()
    legacy.mkdir()
    monkeypatch.setattr(gnome_proxy, "user_data_dir", lambda: current)
    monkeypatch.setattr(gnome_proxy, "data_search_dirs", lambda: (current, legacy))
    payload = {
        "version": 1,
        "state": "applied",
        "created_at": "2026-07-26T00:00:00+00:00",
        "settings": {"org.gnome.system.proxy": {"mode": "'none'"}},
        "applied": {"host": "127.0.0.1", "port": 1080},
    }
    for directory in (current, legacy):
        (directory / "gnome_proxy_journal.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    adapter = GnomeProxyAdapter(
        runner=RestoreRunner(),
        gsettings_path="gsettings",
        available_keys={
            "org.gnome.system.proxy": {"mode"},
            "org.gnome.system.proxy.socks": {"host", "port"},
        },
    )
    assert not adapter.restore_proxy()
    assert "Multiple" in adapter.last_error
    assert all((directory / "gnome_proxy_journal.json").exists() for directory in (current, legacy))


def test_legacy_history_is_listed_and_can_be_deleted(tmp_path, monkeypatch):
    current = tmp_path / "current"
    legacy = tmp_path / "legacy"
    monkeypatch.setattr(result_bundle, "data_search_dirs", lambda: (current, legacy))
    legacy_history = legacy / "history"
    legacy_history.mkdir(parents=True)
    bundle = result_bundle.create_bundle([], [], {}, 0, 1, "completed", 0, 0, 0, 0, {}, {})
    legacy_record = legacy_history / "run_legacy.json"
    result_bundle.save_bundle(legacy_record, bundle)

    assert Path(result_bundle.get_history_dir()) == current / "history"
    records = result_bundle.list_history()
    assert len(records) == 1
    assert Path(records[0]["filepath"]) == legacy_record.resolve()
    result_bundle.delete_history_record(records[0]["filepath"])
    assert not legacy_record.exists()


def test_history_atomic_write_leaves_no_temporary_file(tmp_path):
    destination = tmp_path / "run_test.json"
    bundle = result_bundle.create_bundle([], [], {}, 0, 1, "completed", 0, 0, 0, 0, {}, {})
    result_bundle.save_bundle(destination, bundle)
    assert destination.is_file()
    assert destination.read_bytes().endswith(b"\n")
    assert list(tmp_path.glob("*.tmp")) == []


def test_uninstaller_dry_run_respects_xdg_data_home(tmp_path):
    env = os.environ.copy()
    env["XDG_DATA_HOME"] = str(tmp_path / "custom-data")
    result = subprocess.run(
        ["bash", "scripts/uninstall-user.sh", "--dry-run", "--purge-data", "--prefix", str(tmp_path / "prefix")],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert str(tmp_path / "custom-data") in result.stdout
    assert not (tmp_path / "custom-data").exists()


def test_uninstaller_succeeds_without_journal(tmp_path):
    prefix = tmp_path / "prefix"
    app_dir = prefix / "share/byebyedpi-linux"
    src_dir = app_dir / "src"
    venv_bin = app_dir / ".venv/bin"
    src_dir.mkdir(parents=True)
    venv_bin.mkdir(parents=True)
    (src_dir / "gnome_proxy.py").touch()
    (venv_bin / "python").write_text("#!/bin/sh\nexit 1\n")
    (venv_bin / "python").chmod(0o755)

    env = os.environ.copy()
    env["XDG_DATA_HOME"] = str(tmp_path / "data")

    result = subprocess.run(
        ["bash", "scripts/uninstall-user.sh", "--prefix", str(prefix)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert not app_dir.exists()


def test_uninstaller_aborts_if_journal_present(tmp_path):
    prefix = tmp_path / "prefix"
    app_dir = prefix / "share/byebyedpi-linux"
    src_dir = app_dir / "src"
    venv_bin = app_dir / ".venv/bin"
    src_dir.mkdir(parents=True)
    venv_bin.mkdir(parents=True)
    (src_dir / "gnome_proxy.py").touch()
    (venv_bin / "python").write_text("#!/bin/sh\nexit 1\n")
    (venv_bin / "python").chmod(0o755)

    data_dir = tmp_path / "data" / "ByeByeDPI-Linux"
    data_dir.mkdir(parents=True)
    (data_dir / "gnome_proxy_journal.json").touch()

    env = os.environ.copy()
    env["XDG_DATA_HOME"] = str(tmp_path / "data")

    result = subprocess.run(
        ["bash", "scripts/uninstall-user.sh", "--prefix", str(prefix)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0
    assert app_dir.exists()
    assert (data_dir / "gnome_proxy_journal.json").exists()
