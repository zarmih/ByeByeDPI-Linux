from __future__ import annotations

import hashlib
import inspect
import json
import shutil
import subprocess
import tarfile
from pathlib import Path


def build_release(output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "python3",
            "scripts/build-release.py",
            "--allow-dirty",
            "--version",
            "0.2.0-test",
            "--source-date-epoch",
            "1700000000",
            "--output-dir",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )


def test_release_builder_is_reproducible_and_complete(tmp_path):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first = build_release(first_dir)
    second = build_release(second_dir)
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr

    archive_name = "ByeByeDPI-Linux-0.2.0-test.tar.gz"
    first_archive = first_dir / archive_name
    second_archive = second_dir / archive_name
    assert first_archive.read_bytes() == second_archive.read_bytes()

    digest = hashlib.sha256(first_archive.read_bytes()).hexdigest()
    checksum_line = (first_dir / f"{archive_name}.sha256").read_text().strip()
    assert checksum_line == f"{digest}  {archive_name}"

    with tarfile.open(first_archive, "r:gz") as archive:
        names = set(archive.getnames())
        prefix = "ByeByeDPI-Linux-0.2.0-test/"
        required = {
            prefix + "LICENSE",
            prefix + "THIRD_PARTY_NOTICES.md",
            prefix + "README.md",
            prefix + "SHA256SUMS",
            prefix + "RELEASE-METADATA.json",
            prefix + "scripts/install-user.sh",
            prefix + "vendor/byedpi/LICENSE",
            prefix + "vendor/byedpi/Makefile",
            prefix + "vendor/byedpi/main.c",
        }
        assert required.issubset(names)
        assert prefix + "vendor/byedpi/ciadpi" not in names
        assert not any("/.git/" in name or "/.venv/" in name for name in names)

        metadata_file = archive.extractfile(prefix + "RELEASE-METADATA.json")
        assert metadata_file is not None
        metadata = json.load(metadata_file)
        assert metadata["version"] == "0.2.0-test"
        assert metadata["source_date_epoch"] == 1700000000
        assert len(metadata["main_commit"]) == 40
        assert len(metadata["byedpi_commit"]) == 40


def test_release_archive_installer_dry_run(tmp_path):
    output = tmp_path / "release"
    result = build_release(output)
    assert result.returncode == 0, result.stderr
    archive = output / "ByeByeDPI-Linux-0.2.0-test.tar.gz"
    extract_dir = tmp_path / "extract"
    with tarfile.open(archive, "r:gz") as tar:
        extract_kwargs = {}
        if "filter" in inspect.signature(tar.extractall).parameters:
            extract_kwargs["filter"] = "data"
        tar.extractall(extract_dir, **extract_kwargs)
    root = extract_dir / "ByeByeDPI-Linux-0.2.0-test"

    manifest = subprocess.run(
        ["sha256sum", "-c", "SHA256SUMS"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert manifest.returncode == 0, manifest.stderr

    prefix = tmp_path / "prefix"
    install = subprocess.run(
        ["bash", "scripts/install-user.sh", "--dry-run", "--prefix", str(prefix)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert install.returncode == 0, install.stderr
    assert not prefix.exists()


def test_release_builder_refuses_dirty_tree_without_opt_in(tmp_path):
    marker = Path("release-builder-dirty-marker.tmp")
    marker.write_text("dirty\n", encoding="utf-8")
    try:
        result = subprocess.run(
            [
                "python3",
                "scripts/build-release.py",
                "--version",
                "0.2.0-test",
                "--source-date-epoch",
                "1700000000",
                "--output-dir",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    finally:
        marker.unlink(missing_ok=True)
    assert result.returncode == 1
    assert "Working tree is dirty" in result.stderr

def test_release_builder_ignores_untracked_nested_repository(tmp_path):
    nested = Path("release-builder-nested-repo.tmp")
    nested.mkdir()
    try:
        init = subprocess.run(
            ["git", "init", "-q", str(nested)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert init.returncode == 0, init.stderr
        (nested / "untracked.txt").write_text("not part of the release\n", encoding="utf-8")

        result = build_release(tmp_path / "release")
        assert result.returncode == 0, result.stderr
    finally:
        shutil.rmtree(nested, ignore_errors=True)
