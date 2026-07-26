from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from update_manager import (
    TARGET_ASSETS,
    UPSTREAM_API,
    UpdateError,
    UpdateManager,
    validate_proxy_url,
)


def copy_current_data(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for name in ("strategies.json", "test_targets.json"):
        (data_dir / name).write_bytes((Path("data") / name).read_bytes())
    return data_dir


def make_upstream_fixture(tmp_path: Path, strategy_text: str = "--split 1\n--fake 1\n") -> Path:
    root = tmp_path / "upstream"
    assets = root / "app" / "src" / "main" / "assets"
    assets.mkdir(parents=True)
    (assets / "proxytest_strategies.list").write_text(strategy_text, encoding="utf-8")
    for index, filename in enumerate(TARGET_ASSETS):
        stem = filename.removeprefix("proxytest_").removesuffix(".sites")
        (assets / filename).write_text(
            f"{stem}.example.com\n{stem}{index}.example.net\n",
            encoding="utf-8",
        )
    return root


def test_proxy_url_validation():
    assert validate_proxy_url("http://127.0.0.1:10808") == "http://127.0.0.1:10808"
    assert validate_proxy_url("") is None
    with pytest.raises(UpdateError, match="credentials"):
        validate_proxy_url("http://user:pass@localhost:8080")
    with pytest.raises(UpdateError):
        validate_proxy_url("socks5://127.0.0.1:1080")


def test_preview_local_strategies_diff_apply_and_rollback(tmp_path):
    data_dir = copy_current_data(tmp_path)
    backup_dir = tmp_path / "backups"
    upstream = make_upstream_fixture(tmp_path, "--split 42\n--fake 1\n")
    manager = UpdateManager(data_dir, backup_dir=backup_dir)
    original = (data_dir / "strategies.json").read_bytes()

    preview = manager.preview_local("strategies", upstream, commit="a" * 40)
    assert preview.kind == "strategies"
    assert preview.source_commit == "a" * 40
    assert preview.diff["candidate_count"] == 2
    assert preview.diff["removed_count"] >= 58
    assert "Commit: " + "a" * 40 in preview.report()

    backup = manager.apply(preview)
    assert backup.is_file()
    installed = json.loads((data_dir / "strategies.json").read_text(encoding="utf-8"))
    assert installed["metadata"]["upstream_commit"] == "a" * 40
    assert installed["strategies"][0]["args"] == "--split 42"

    restored_from = manager.rollback("strategies", backup)
    assert restored_from == backup.resolve()
    assert (data_dir / "strategies.json").read_bytes() == original


def test_preview_local_targets_apply_and_rollback(tmp_path):
    data_dir = copy_current_data(tmp_path)
    manager = UpdateManager(data_dir, backup_dir=tmp_path / "backups")
    upstream = make_upstream_fixture(tmp_path)
    original = (data_dir / "test_targets.json").read_bytes()

    preview = manager.preview_local("targets", upstream, commit="fixture")
    assert preview.diff["candidate_count"] == 16
    assert preview.candidate["metadata"]["total_groups"] == 8
    assert preview.candidate["metadata"]["total_targets"] == 16
    backup = manager.apply(preview)
    manager.rollback("targets", backup)
    assert (data_dir / "test_targets.json").read_bytes() == original


def test_candidate_tampering_is_rejected(tmp_path):
    data_dir = copy_current_data(tmp_path)
    manager = UpdateManager(data_dir, backup_dir=tmp_path / "backups")
    upstream = make_upstream_fixture(tmp_path)
    preview = manager.preview_local("strategies", upstream)
    preview.candidate["strategies"][0]["args"] = "--tampered"
    with pytest.raises(UpdateError, match="changed after validation"):
        manager.apply(preview)
    assert manager.list_backups() == []


def test_invalid_strategy_and_target_payloads_are_rejected():
    with pytest.raises(UpdateError):
        UpdateManager.validate_strategies({"strategies": [{"id": "x", "args": ""}]})
    with pytest.raises(UpdateError, match="Duplicate"):
        UpdateManager.validate_strategies(
            {"strategies": [{"id": "x", "args": "a"}, {"id": "x", "args": "b"}]}
        )
    with pytest.raises(UpdateError, match="Duplicate strategy arguments"):
        UpdateManager.validate_strategies(
            {"strategies": [{"id": "x", "args": "same"}, {"id": "y", "args": "same"}]}
        )
    with pytest.raises(UpdateError, match="Invalid target host"):
        UpdateManager.validate_targets(
            {
                "groups": [
                    {
                        "group_id": "g",
                        "targets": [
                            {"target_id": "t", "host": "bad host", "url": "https://bad host/"}
                        ],
                    }
                ]
            }
        )



    with pytest.raises(UpdateError, match="Duplicate target host"):
        UpdateManager.validate_targets(
            {
                "groups": [
                    {
                        "group_id": "g",
                        "targets": [
                            {"target_id": "t1", "host": "same.example", "url": "https://same.example/"},
                            {"target_id": "t2", "host": "same.example", "url": "https://same.example/"},
                        ],
                    }
                ]
            }
        )


def test_rollback_rejects_path_outside_backup_dir(tmp_path):
    data_dir = copy_current_data(tmp_path)
    manager = UpdateManager(data_dir, backup_dir=tmp_path / "backups")
    outside = tmp_path / "strategies_outside.json"
    outside.write_bytes((data_dir / "strategies.json").read_bytes())
    with pytest.raises(UpdateError, match="outside"):
        manager.rollback("strategies", outside)


def test_remote_preview_pins_assets_to_returned_commit(tmp_path):
    data_dir = copy_current_data(tmp_path)
    commit = "b" * 40
    requested = []

    def fetcher(url: str, proxy: str | None) -> bytes:
        requested.append((url, proxy))
        if url == UPSTREAM_API:
            return json.dumps({"sha": commit}).encode()
        if url.endswith("proxytest_strategies.list"):
            assert f"/{commit}/" in url
            return b"--split 1\n"
        raise AssertionError(url)

    manager = UpdateManager(data_dir, backup_dir=tmp_path / "backups", fetcher=fetcher)
    preview = manager.preview_remote("strategies", "http://127.0.0.1:10808")
    assert preview.source_commit == commit
    assert all(proxy == "http://127.0.0.1:10808" for _, proxy in requested)


def test_backup_retention_is_limited(tmp_path):
    data_dir = copy_current_data(tmp_path)
    backup_dir = tmp_path / "backups"
    manager = UpdateManager(data_dir, backup_dir=backup_dir)
    upstream = make_upstream_fixture(tmp_path)
    for index in range(12):
        preview = manager.preview_local(
            "strategies",
            upstream,
            commit=f"fixture-{index}",
        )
        manager.apply(preview)
    assert len(manager.list_backups("strategies")) == 10
