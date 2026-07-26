from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from update_manager import TARGET_ASSETS


def create_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "upstream"
    assets = root / "app" / "src" / "main" / "assets"
    assets.mkdir(parents=True)
    (assets / "proxytest_strategies.list").write_text("--split 7\n--fake 2\n", encoding="utf-8")
    for index, filename in enumerate(TARGET_ASSETS):
        (assets / filename).write_text(
            f"group{index}.example.com\ngroup{index}.example.net\n",
            encoding="utf-8",
        )
    return root


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_strategy_cli_dry_run_does_not_change_active_data(tmp_path):
    fixture = create_fixture(tmp_path)
    active = Path("data/strategies.json")
    before = digest(active)
    result = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/update_strategies.py",
            "--dry-run",
            "--local-dir",
            str(fixture),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "Dry run complete" in result.stdout
    assert "Candidate Count: 2" in result.stdout
    assert digest(active) == before


def test_targets_cli_exports_validated_candidate(tmp_path):
    fixture = create_fixture(tmp_path)
    output = tmp_path / "candidate-targets.json"
    result = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/update_test_targets.py",
            "--local-dir",
            str(fixture),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["metadata"]["total_groups"] == 8
    assert data["metadata"]["total_targets"] == 16
    assert "Exported validated candidate" in result.stdout


def test_cli_rejects_unsafe_proxy_without_network():
    result = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/update_strategies.py",
            "--dry-run",
            "--proxy",
            "socks5://127.0.0.1:1080",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "http:// or https://" in result.stderr
