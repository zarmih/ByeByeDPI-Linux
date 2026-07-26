from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from paths import user_data_dir


UPSTREAM_REPO = "romanvht/ByeByeDPI"
UPSTREAM_API = f"https://api.github.com/repos/{UPSTREAM_REPO}/commits/master"
RAW_BASE = f"https://raw.githubusercontent.com/{UPSTREAM_REPO}"
STRATEGIES_ASSET = "app/src/main/assets/proxytest_strategies.list"
TARGET_ASSETS = (
    "proxytest_cloudflare.sites",
    "proxytest_discord.sites",
    "proxytest_general.sites",
    "proxytest_googlevideo.sites",
    "proxytest_social.sites",
    "proxytest_telegram.sites",
    "proxytest_türkiye.sites",
    "proxytest_youtube.sites",
)
DEFAULT_ACTIVE_GROUPS = {"youtube", "googlevideo"}
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
MAX_JSON_BYTES = 20 * 1024 * 1024
MAX_STRATEGIES = 1000
MAX_TARGETS = 10000
BACKUP_LIMIT = 10
HOST_RE = re.compile(r"^(?=.{1,253}$)(?:[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?\.)*[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?$")


class UpdateError(RuntimeError):
    """Raised for download, validation, apply, or rollback failures."""


Fetcher = Callable[[str, str | None], bytes]


@dataclass(frozen=True)
class UpdatePreview:
    kind: str
    source_commit: str
    candidate: dict
    diff: dict
    candidate_sha256: str

    def report(self) -> str:
        lines = [
            f"Kind: {self.kind}",
            f"Source: https://github.com/{UPSTREAM_REPO}",
            f"Commit: {self.source_commit}",
            f"Candidate SHA-256: {self.candidate_sha256}",
        ]
        for key in (
            "current_count",
            "candidate_count",
            "added_count",
            "removed_count",
            "changed_count",
        ):
            lines.append(f"{key.replace('_', ' ').title()}: {self.diff.get(key, 0)}")
        lines.append(f"Metadata Changed: {bool(self.diff.get('metadata_changed'))}")
        if self.diff.get("current_source_commit"):
            lines.append(f"Current Source Commit: {self.diff['current_source_commit']}")
        for key in ("added", "removed", "changed"):
            values = self.diff.get(key, [])
            if values:
                preview = ", ".join(values[:25])
                suffix = " …" if len(values) > 25 else ""
                lines.append(f"{key.title()}: {preview}{suffix}")
        return "\n".join(lines)


def validate_proxy_url(proxy: str | None) -> str | None:
    if proxy is None or not proxy.strip():
        return None
    value = proxy.strip()
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UpdateError("Update proxy must be an http:// or https:// URL")
    if parsed.username is not None or parsed.password is not None:
        raise UpdateError("Proxy credentials are not stored or accepted in the update URL")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise UpdateError("Update proxy URL must contain only scheme, host, and optional port")
    try:
        port = parsed.port
    except ValueError as exc:
        raise UpdateError("Invalid update proxy port") from exc
    if port is not None and not 1 <= port <= 65535:
        raise UpdateError("Invalid update proxy port")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))




def _normalize_host(value: str) -> str:
    host = value.strip().lower().rstrip(".")
    if not host:
        raise UpdateError("Target host is empty")
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UpdateError(f"Invalid target host: {value!r}") from exc
    if not HOST_RE.fullmatch(ascii_host):
        raise UpdateError(f"Invalid target host: {value!r}")
    return ascii_host

def _safe_json_bytes(data: Mapping) -> bytes:
    encoded = (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n").encode("utf-8")
    if len(encoded) > MAX_JSON_BYTES:
        raise UpdateError("Validated update JSON exceeds the safety limit")
    return encoded


def _sha256_json(data: Mapping) -> str:
    return hashlib.sha256(_safe_json_bytes(data)).hexdigest()


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise UpdateError(f"Data file is missing: {path}")
    if path.stat().st_size > MAX_JSON_BYTES:
        raise UpdateError(f"Data file is too large: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UpdateError(f"Invalid JSON in {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise UpdateError(f"Top level of {path.name} must be an object")
    return value


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _default_backup_dir() -> Path:
    return user_data_dir() / "updates" / "backups"


class UpdateManager:
    def __init__(
        self,
        data_dir: str | os.PathLike[str],
        *,
        backup_dir: str | os.PathLike[str] | None = None,
        fetcher: Fetcher | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.backup_dir = Path(backup_dir) if backup_dir is not None else _default_backup_dir()
        self._fetcher = fetcher or self._fetch_url

    @staticmethod
    def _fetch_url(url: str, proxy: str | None) -> bytes:
        handlers = []
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        opener = urllib.request.build_opener(*handlers)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "ByeByeDPI-Linux-Updater/1.0", "Accept": "application/json,text/plain"},
        )
        try:
            with opener.open(request, timeout=30) as response:
                declared = response.headers.get("Content-Length")
                if declared and int(declared) > MAX_DOWNLOAD_BYTES:
                    raise UpdateError("Upstream response exceeds the download limit")
                payload = response.read(MAX_DOWNLOAD_BYTES + 1)
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
            raise UpdateError(f"Failed to fetch {url}: {exc}") from exc
        if len(payload) > MAX_DOWNLOAD_BYTES:
            raise UpdateError("Upstream response exceeds the download limit")
        return payload

    def _latest_commit(self, proxy: str | None) -> str:
        payload = self._fetcher(UPSTREAM_API, proxy)
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise UpdateError("GitHub returned invalid commit metadata") from exc
        commit = data.get("sha") if isinstance(data, dict) else None
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
            raise UpdateError("GitHub commit metadata did not contain a full SHA")
        return commit.lower()

    def _asset_bytes(self, commit: str, asset_path: str, proxy: str | None) -> bytes:
        quoted = "/".join(urllib.parse.quote(part) for part in asset_path.split("/"))
        return self._fetcher(f"{RAW_BASE}/{commit}/{quoted}", proxy)

    @staticmethod
    def _decode_text(payload: bytes, name: str) -> str:
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UpdateError(f"Upstream asset is not UTF-8: {name}") from exc

    def preview_remote(self, kind: str, proxy: str | None = None) -> UpdatePreview:
        safe_proxy = validate_proxy_url(proxy)
        commit = self._latest_commit(safe_proxy)
        if kind == "strategies":
            text = self._decode_text(
                self._asset_bytes(commit, STRATEGIES_ASSET, safe_proxy), STRATEGIES_ASSET
            )
            candidate = self.build_strategies(text, commit, f"github:{UPSTREAM_REPO}@{commit}")
        elif kind == "targets":
            contents = {}
            for filename in TARGET_ASSETS:
                asset = f"app/src/main/assets/{filename}"
                contents[filename] = self._decode_text(
                    self._asset_bytes(commit, asset, safe_proxy), filename
                )
            candidate = self.build_targets(contents, commit, f"github:{UPSTREAM_REPO}@{commit}")
        else:
            raise UpdateError(f"Unsupported update kind: {kind}")
        return self._make_preview(kind, commit, candidate)

    def preview_local(
        self,
        kind: str,
        upstream_root: str | os.PathLike[str],
        *,
        commit: str = "local-fixture",
    ) -> UpdatePreview:
        assets = Path(upstream_root) / "app" / "src" / "main" / "assets"
        if kind == "strategies":
            path = assets / Path(STRATEGIES_ASSET).name
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise UpdateError(f"Cannot read local strategy fixture: {exc}") from exc
            candidate = self.build_strategies(
                text, commit, f"local:{Path(upstream_root).name}"
            )
        elif kind == "targets":
            contents = {}
            for filename in TARGET_ASSETS:
                try:
                    contents[filename] = (assets / filename).read_text(encoding="utf-8")
                except (OSError, UnicodeError) as exc:
                    raise UpdateError(f"Cannot read local target fixture {filename}: {exc}") from exc
            candidate = self.build_targets(
                contents, commit, f"local:{Path(upstream_root).name}"
            )
        else:
            raise UpdateError(f"Unsupported update kind: {kind}")
        return self._make_preview(kind, commit, candidate)

    @staticmethod
    def build_strategies(text: str, commit: str, source: str) -> dict:
        args_lines = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        strategies = []
        for index, args in enumerate(args_lines, 1):
            strategies.append(
                {
                    "id": f"strategy_{index}",
                    "name": f"Strategy {index}",
                    "args": args,
                    "source": source,
                    "upstream_commit": commit,
                    "enabled": True,
                    "supported": True,
                    "notes": (
                        "Placeholder {sni} is replaced with the selected target host during testing."
                        if "{sni}" in args
                        else ""
                    ),
                }
            )
        candidate = {
            "metadata": {
                "upstream_repo": UPSTREAM_REPO,
                "upstream_commit": commit,
                "asset_path": STRATEGIES_ASSET,
                "total_strategies": len(strategies),
                "format_version": 1,
            },
            "strategies": strategies,
        }
        UpdateManager.validate_strategies(candidate)
        return candidate

    @staticmethod
    def build_targets(contents: Mapping[str, str], commit: str, source: str) -> dict:
        groups = []
        total = 0
        for filename in TARGET_ASSETS:
            if filename not in contents:
                raise UpdateError(f"Missing target asset: {filename}")
            group_id = filename.removeprefix("proxytest_").removesuffix(".sites")
            domains = []
            seen = set()
            for raw_line in contents[filename].splitlines():
                raw_domain = raw_line.strip()
                if not raw_domain or raw_domain.startswith("#"):
                    continue
                domain = _normalize_host(raw_domain)
                if domain not in seen:
                    domains.append(domain)
                    seen.add(domain)
            targets = []
            for index, domain in enumerate(domains):
                targets.append(
                    {
                        "target_id": f"{group_id}_{index}",
                        "label": domain,
                        "host": domain,
                        "url": f"https://{domain}/",
                        "test_type": "http_head",
                        "notes": "",
                    }
                )
            total += len(targets)
            groups.append(
                {
                    "group_id": group_id,
                    "group_name": group_id.capitalize(),
                    "enabled_by_default": group_id in DEFAULT_ACTIVE_GROUPS,
                    "source": f"{source}/{filename}",
                    "upstream_commit": commit,
                    "targets": targets,
                }
            )
        candidate = {
            "metadata": {
                "upstream_repo": UPSTREAM_REPO,
                "upstream_commit": commit,
                "total_groups": len(groups),
                "total_targets": total,
                "format_version": 1,
            },
            "groups": groups,
        }
        UpdateManager.validate_targets(candidate)
        return candidate

    @staticmethod
    def validate_strategies(data: Mapping) -> None:
        strategies = data.get("strategies") if isinstance(data, Mapping) else None
        if not isinstance(strategies, list) or not 1 <= len(strategies) <= MAX_STRATEGIES:
            raise UpdateError("Strategy update must contain 1..1000 strategies")
        ids = set()
        args_seen = set()
        for item in strategies:
            if not isinstance(item, dict):
                raise UpdateError("Each strategy must be an object")
            strategy_id = item.get("id")
            args = item.get("args")
            if not isinstance(strategy_id, str) or not strategy_id or len(strategy_id) > 128:
                raise UpdateError("Invalid strategy ID")
            if strategy_id in ids:
                raise UpdateError(f"Duplicate strategy ID: {strategy_id}")
            ids.add(strategy_id)
            if not isinstance(args, str) or not args.strip() or len(args) > 16384 or "\x00" in args:
                raise UpdateError(f"Invalid arguments for {strategy_id}")
            if args in args_seen:
                raise UpdateError(f"Duplicate strategy arguments: {strategy_id}")
            args_seen.add(args)
        metadata = data.get("metadata", {})
        if metadata and not isinstance(metadata, Mapping):
            raise UpdateError("Strategy metadata must be an object")

    @staticmethod
    def validate_targets(data: Mapping) -> None:
        groups = data.get("groups") if isinstance(data, Mapping) else None
        if not isinstance(groups, list) or not 1 <= len(groups) <= 100:
            raise UpdateError("Target update must contain 1..100 groups")
        group_ids = set()
        target_ids = set()
        hosts_seen = set()
        total = 0
        for group in groups:
            if not isinstance(group, dict):
                raise UpdateError("Each target group must be an object")
            group_id = group.get("group_id")
            targets = group.get("targets")
            if not isinstance(group_id, str) or not group_id or group_id in group_ids:
                raise UpdateError("Invalid or duplicate target group ID")
            group_ids.add(group_id)
            if not isinstance(targets, list):
                raise UpdateError(f"Targets for {group_id} must be a list")
            for target in targets:
                if not isinstance(target, dict):
                    raise UpdateError("Each target must be an object")
                target_id = target.get("target_id")
                host = target.get("host")
                url = target.get("url")
                if not isinstance(target_id, str) or not target_id or target_id in target_ids:
                    raise UpdateError("Invalid or duplicate target ID")
                target_ids.add(target_id)
                if not isinstance(host, str) or _normalize_host(host) != host.lower():
                    raise UpdateError(f"Invalid target host: {host!r}")
                if host in hosts_seen:
                    raise UpdateError(f"Duplicate target host: {host}")
                hosts_seen.add(host)
                if not isinstance(url, str):
                    raise UpdateError(f"Invalid URL for {target_id}")
                parsed = urllib.parse.urlsplit(url)
                if parsed.scheme not in {"http", "https"} or parsed.hostname != host:
                    raise UpdateError(f"Invalid URL for {target_id}")
                total += 1
                if total > MAX_TARGETS:
                    raise UpdateError("Target update exceeds 10000 targets")
        if total < 1:
            raise UpdateError("Target update contains no targets")

    def _data_path(self, kind: str) -> Path:
        if kind == "strategies":
            return self.data_dir / "strategies.json"
        if kind == "targets":
            return self.data_dir / "test_targets.json"
        raise UpdateError(f"Unsupported update kind: {kind}")

    def _current(self, kind: str) -> dict:
        current = _read_json(self._data_path(kind))
        if kind == "strategies":
            self.validate_strategies(current)
        else:
            self.validate_targets(current)
        return current

    @staticmethod
    def _strategy_map(data: Mapping) -> dict[str, dict]:
        return {
            item["id"]: {
                "args": item.get("args", ""),
                "enabled": bool(item.get("enabled", True)),
                "supported": bool(item.get("supported", True)),
            }
            for item in data.get("strategies", [])
        }

    @staticmethod
    def _target_map(data: Mapping) -> dict[str, dict]:
        result = {}
        for group in data.get("groups", []):
            for target in group.get("targets", []):
                result[target["target_id"]] = {
                    "group_id": group.get("group_id"),
                    "enabled_by_default": bool(group.get("enabled_by_default", False)),
                    "host": target.get("host"),
                    "url": target.get("url"),
                    "test_type": target.get("test_type"),
                }
        return result

    @staticmethod
    def _diff_maps(current: Mapping[str, dict], candidate: Mapping[str, dict]) -> dict:
        current_ids = set(current)
        candidate_ids = set(candidate)
        added = sorted(candidate_ids - current_ids)
        removed = sorted(current_ids - candidate_ids)
        changed = sorted(
            key for key in current_ids & candidate_ids if current[key] != candidate[key]
        )
        return {
            "current_count": len(current),
            "candidate_count": len(candidate),
            "added_count": len(added),
            "removed_count": len(removed),
            "changed_count": len(changed),
            "added": added,
            "removed": removed,
            "changed": changed,
        }

    def _make_preview(self, kind: str, commit: str, candidate: dict) -> UpdatePreview:
        current = self._current(kind)
        if kind == "strategies":
            diff = self._diff_maps(self._strategy_map(current), self._strategy_map(candidate))
            current_commit = current.get("metadata", {}).get("upstream_commit")
            if not current_commit:
                item_commits = {
                    item.get("upstream_commit")
                    for item in current.get("strategies", [])
                    if item.get("upstream_commit")
                }
                current_commit = next(iter(item_commits)) if len(item_commits) == 1 else None
        else:
            diff = self._diff_maps(self._target_map(current), self._target_map(candidate))
            current_commit = current.get("metadata", {}).get("upstream_commit")
        diff["current_source_commit"] = current_commit
        diff["metadata_changed"] = current_commit != commit
        return UpdatePreview(
            kind=kind,
            source_commit=commit,
            candidate=copy.deepcopy(candidate),
            diff=diff,
            candidate_sha256=_sha256_json(candidate),
        )

    def export_candidate(
        self,
        preview: UpdatePreview,
        destination: str | os.PathLike[str],
    ) -> Path:
        candidate = copy.deepcopy(preview.candidate)
        if preview.kind == "strategies":
            self.validate_strategies(candidate)
        elif preview.kind == "targets":
            self.validate_targets(candidate)
        else:
            raise UpdateError("Invalid preview kind")
        if _sha256_json(candidate) != preview.candidate_sha256:
            raise UpdateError("Preview candidate changed after validation")
        path = Path(destination)
        _atomic_write(path, _safe_json_bytes(candidate))
        written = _read_json(path)
        if _sha256_json(written) != preview.candidate_sha256:
            raise UpdateError("Export verification failed")
        return path

    def apply(self, preview: UpdatePreview) -> Path:
        if preview.kind not in {"strategies", "targets"}:
            raise UpdateError("Invalid preview kind")
        candidate = copy.deepcopy(preview.candidate)
        if preview.kind == "strategies":
            self.validate_strategies(candidate)
        else:
            self.validate_targets(candidate)
        if _sha256_json(candidate) != preview.candidate_sha256:
            raise UpdateError("Preview candidate changed after validation")

        target = self._data_path(preview.kind)
        current_payload = target.read_bytes()
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        backup = self.backup_dir / f"{preview.kind}_{timestamp}_{hashlib.sha256(current_payload).hexdigest()[:12]}.json"
        _atomic_write(backup, current_payload)
        try:
            _atomic_write(target, _safe_json_bytes(candidate))
            written = self._current(preview.kind)
            if _sha256_json(written) != preview.candidate_sha256:
                raise UpdateError("Post-write verification failed")
        except (OSError, UpdateError) as exc:
            try:
                _atomic_write(target, current_payload)
            except OSError as rollback_exc:
                raise UpdateError(f"Update failed and automatic rollback failed: {rollback_exc}") from exc
            raise UpdateError(f"Update failed; previous data was restored: {exc}") from exc
        self._prune_backups(preview.kind)
        return backup

    def list_backups(self, kind: str | None = None) -> list[Path]:
        if not self.backup_dir.is_dir():
            return []
        prefix = f"{kind}_" if kind else ""
        backups = [
            path for path in self.backup_dir.glob(f"{prefix}*.json")
            if path.is_file() and path.name.startswith(("strategies_", "targets_"))
        ]
        return sorted(backups, key=lambda path: path.stat().st_mtime, reverse=True)

    def _prune_backups(self, kind: str) -> None:
        for old in self.list_backups(kind)[BACKUP_LIMIT:]:
            try:
                old.unlink()
            except OSError:
                pass

    def rollback(self, kind: str, backup: str | os.PathLike[str] | None = None) -> Path:
        backup_path = Path(backup) if backup is not None else next(iter(self.list_backups(kind)), None)
        if backup_path is None:
            raise UpdateError(f"No backup is available for {kind}")
        try:
            resolved_backup = backup_path.resolve(strict=True)
            resolved_root = self.backup_dir.resolve(strict=True)
            resolved_backup.relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            raise UpdateError("Backup path is outside the update backup directory") from exc
        if not resolved_backup.name.startswith(f"{kind}_"):
            raise UpdateError("Backup kind does not match rollback request")
        if resolved_backup.stat().st_size > MAX_JSON_BYTES:
            raise UpdateError("Backup file exceeds the safety limit")
        try:
            backup_payload = resolved_backup.read_bytes()
            data = json.loads(backup_payload.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise UpdateError(f"Invalid backup JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise UpdateError("Backup JSON must contain an object")
        if kind == "strategies":
            self.validate_strategies(data)
        elif kind == "targets":
            self.validate_targets(data)
        else:
            raise UpdateError(f"Unsupported update kind: {kind}")
        target = self._data_path(kind)
        _atomic_write(target, backup_payload)
        self._current(kind)
        return resolved_backup
