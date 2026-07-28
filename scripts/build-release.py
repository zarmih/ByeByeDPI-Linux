#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
SUBMODULE = ROOT / "vendor" / "byedpi"
DEFAULT_OUTPUT = ROOT / "dist"
EXCLUDED_PREFIXES = (
    ".git/",
    ".venv/",
    "dist/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
)
REQUIRED_RELEASE_FILES = (
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "README.md",
    "requirements-runtime.txt",
    "scripts/install-user.sh",
    "scripts/uninstall-user.sh",
    "vendor/byedpi/LICENSE",
    "vendor/byedpi/Makefile",
)


class ReleaseError(RuntimeError):
    pass


def run_git(args: list[str], *, cwd: Path = ROOT) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReleaseError(f"Git command failed to start: {exc}") from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "unknown git error").strip()
        raise ReleaseError(f"git {' '.join(args)}: {message}")
    return result.stdout.strip()


def project_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise ReleaseError("Cannot find project version in pyproject.toml")
    return match.group(1)


def validate_version(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", value):
        raise ReleaseError("Version contains unsafe characters")
    return value


def git_paths(cwd: Path, *, include_untracked: bool) -> list[str]:
    tracked = run_git(["ls-files", "-z"], cwd=cwd).split("\0")
    paths = [path for path in tracked if path]
    if include_untracked:
        extra = run_git(
            ["ls-files", "--others", "--exclude-standard", "-z"], cwd=cwd
        ).split("\0")
        paths.extend(path for path in extra if path)
    return sorted(set(paths))


def excluded(relative: str) -> bool:
    normalized = relative.replace(os.sep, "/")
    return any(normalized == prefix.rstrip("/") or normalized.startswith(prefix) for prefix in EXCLUDED_PREFIXES)


def copy_entry(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        destination.symlink_to(os.readlink(source))
    elif source.is_file():
        shutil.copy2(source, destination)
    else:
        raise ReleaseError(f"Tracked entry is missing or unsupported: {source}")


def copy_repository(staging_root: Path, *, include_untracked: bool) -> int:
    copied = 0
    for relative in git_paths(ROOT, include_untracked=include_untracked):
        if relative == "vendor/byedpi" or excluded(relative):
            continue
        source = ROOT / relative
        if not source.exists() and not source.is_symlink():
            continue
        if source.is_dir():
            continue
        copy_entry(source, staging_root / relative)
        copied += 1

    if not (SUBMODULE / ".git").exists() and not (SUBMODULE / "Makefile").is_file():
        raise ReleaseError("vendor/byedpi submodule is missing; clone with --recurse-submodules")
    for relative in git_paths(SUBMODULE, include_untracked=False):
        source = SUBMODULE / relative
        if not source.exists() and not source.is_symlink():
            continue
        copy_entry(source, staging_root / "vendor" / "byedpi" / relative)
        copied += 1
    return copied


def normalize_tree(root: Path, epoch: int) -> None:
    entries = sorted(root.rglob("*"), key=lambda path: len(path.parts), reverse=True)
    for path in entries:
        if path.is_symlink():
            try:
                os.utime(path, (epoch, epoch), follow_symlinks=False)
            except (NotImplementedError, OSError):
                pass
            continue
        if path.is_dir():
            path.chmod(0o755)
        elif path.is_file():
            original = path.stat().st_mode
            path.chmod(0o755 if original & stat.S_IXUSR else 0o644)
        os.utime(path, (epoch, epoch))
    root.chmod(0o755)
    os.utime(root, (epoch, epoch))


def write_manifest(root: Path) -> None:
    lines = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "SHA256SUMS":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(root).as_posix()}")
    (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def add_tar_member(archive: tarfile.TarFile, source: Path, arcname: str, epoch: int) -> None:
    info = archive.gettarinfo(str(source), arcname=arcname)
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = epoch
    if info.isdir():
        info.mode = 0o755
    elif info.isfile():
        info.mode = 0o755 if source.stat().st_mode & stat.S_IXUSR else 0o644
    if info.isfile():
        with source.open("rb") as handle:
            archive.addfile(info, handle)
    else:
        archive.addfile(info)


def create_archive(source_root: Path, top_name: str, destination: Path, epoch: int) -> None:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=9,
                fileobj=raw,
                mtime=epoch,
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed,
                    mode="w",
                    format=tarfile.GNU_FORMAT,
                ) as archive:
                    add_tar_member(archive, source_root, top_name, epoch)
                    for path in sorted(source_root.rglob("*")):
                        relative = path.relative_to(source_root).as_posix()
                        add_tar_member(archive, path, f"{top_name}/{relative}", epoch)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def verify_archive(path: Path, top_name: str) -> None:
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            names = {member.name for member in members}
            for member in members:
                pure = PurePosixPath(member.name)
                if pure.is_absolute() or ".." in pure.parts:
                    raise ReleaseError(f"Unsafe archive member: {member.name}")
                if not member.name.startswith(top_name):
                    raise ReleaseError(f"Unexpected archive root: {member.name}")
                if member.mode & (stat.S_ISUID | stat.S_ISGID):
                    raise ReleaseError(f"Unsafe archive permissions: {member.name}")
            for required in REQUIRED_RELEASE_FILES:
                expected = f"{top_name}/{required}"
                if expected not in names:
                    raise ReleaseError(f"Release archive is missing {required}")
            if f"{top_name}/vendor/byedpi/ciadpi" in names:
                raise ReleaseError("Untracked ciadpi binary leaked into source archive")
            for source_name in ("main.c", "proxy.c", "desync.c", "packets.c"):
                expected_source = f"{top_name}/vendor/byedpi/{source_name}"
                if expected_source not in names:
                    raise ReleaseError(
                        f"ByeDPI submodule source is missing: {source_name}"
                    )
    except (OSError, tarfile.TarError) as exc:
        raise ReleaseError(f"Cannot verify release archive: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic ByeByeDPI-Linux source release")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--version", default=project_version())
    parser.add_argument("--source-date-epoch", type=int)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    version = validate_version(args.version)
    output_dir = Path(args.output_dir).expanduser().resolve()
    status = run_git(["status", "--porcelain", "--untracked-files=normal"])
    submodule_status = run_git(["status", "--porcelain", "--untracked-files=no"], cwd=SUBMODULE)
    dirty = bool(status or submodule_status)
    if dirty and not args.allow_dirty:
        raise ReleaseError("Working tree is dirty; commit changes or pass --allow-dirty")

    epoch = args.source_date_epoch
    if epoch is None:
        environment_epoch = os.environ.get("SOURCE_DATE_EPOCH")
        epoch = int(environment_epoch) if environment_epoch else int(run_git(["log", "-1", "--format=%ct"]))
    if epoch < 0:
        raise ReleaseError("SOURCE_DATE_EPOCH cannot be negative")

    main_commit = run_git(["rev-parse", "HEAD"])
    byedpi_commit = run_git(["rev-parse", "HEAD"], cwd=SUBMODULE)
    top_name = f"ByeByeDPI-Linux-{version}"
    archive_name = f"{top_name}.tar.gz"

    if args.dry_run:
        print(f"Version: {version}")
        print(f"Source date epoch: {epoch}")
        print(f"Main commit: {main_commit}")
        print(f"ByeDPI commit: {byedpi_commit}")
        print(f"Dirty working tree: {dirty}")
        print(f"Output: {output_dir / archive_name}")
        print("Dry run complete. No files were created.")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / archive_name
    with tempfile.TemporaryDirectory(prefix="byebyedpi-release-") as temporary:
        release_root = Path(temporary) / top_name
        release_root.mkdir()
        copied = copy_repository(release_root, include_untracked=args.allow_dirty)
        metadata = {
            "name": "ByeByeDPI-Linux",
            "version": version,
            "source_date_epoch": epoch,
            "source_date_utc": dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat(),
            "main_commit": main_commit,
            "byedpi_commit": byedpi_commit,
            "dirty_working_tree": dirty,
            "copied_file_count_before_metadata": copied,
        }
        (release_root / "RELEASE-METADATA.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        write_manifest(release_root)
        normalize_tree(release_root, epoch)
        create_archive(release_root, top_name, destination, epoch)

    verify_archive(destination, top_name)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    checksum = destination.with_suffix(destination.suffix + ".sha256")
    checksum.write_text(f"{digest}  {destination.name}\n", encoding="utf-8")
    print(f"Created: {destination}")
    print(f"SHA-256: {digest}")
    print(f"Checksum: {checksum}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReleaseError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
