from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Mapping

JOURNAL_VERSION = 1
MAX_JOURNAL_BYTES = 1024 * 1024
CONFIG_FILE = "kioslaverc"
CONFIG_GROUP = "Proxy Settings"
MISSING_SENTINEL = "__BYEBYEDPI_KCONFIG_MISSING_2F3B17B4__"

# Only settings that ByeByeDPI mutates are journaled. This avoids overwriting
# unrelated KIO settings if the user changes them while ByeByeDPI is running.
MANAGED_KEYS = (
    "httpProxy",
    "httpsProxy",
    "ftpProxy",
    "socksProxy",
    "ReversedException",
    "ProxyType",
)


class KdeProxyIntegrationError(RuntimeError):
    """Raised when KDE proxy settings cannot be changed or restored safely."""


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _detect_kconfig_tools() -> tuple[str | None, str | None]:
    for suffix in ("6", "5", ""):
        reader = shutil.which(f"kreadconfig{suffix}")
        writer = shutil.which(f"kwriteconfig{suffix}")
        if reader and writer:
            return reader, writer
    return None, None


class KdeProxyAdapter:
    """User-level KDE/KIO SOCKS proxy integration with crash-safe rollback.

    The adapter uses KDE's own kreadconfig/kwriteconfig tools, never root access,
    and mutates only the Proxy Settings keys listed in ``MANAGED_KEYS``.
    """

    integration_name = "KDE/KIO"

    def __init__(
        self,
        *,
        runner: Runner | None = None,
        data_dir: str | os.PathLike[str] | None = None,
        kreadconfig_path: str | None = None,
        kwriteconfig_path: str | None = None,
        notify_supported: bool | None = None,
    ) -> None:
        self._runner = runner or subprocess.run
        detected_reader, detected_writer = _detect_kconfig_tools()
        self.kreadconfig_path = kreadconfig_path or detected_reader
        self.kwriteconfig_path = kwriteconfig_path or detected_writer
        self.last_error = ""
        self._notify_supported = notify_supported

        if data_dir is not None:
            app_dir = Path(data_dir)
            journal_dirs = (app_dir,)
        else:
            from paths import data_search_dirs, user_data_dir

            app_dir = user_data_dir()
            journal_dirs = data_search_dirs()
        app_dir.mkdir(parents=True, exist_ok=True)
        self.journal_file = str(app_dir / "kde_proxy_journal.json")
        self._journal_candidates = tuple(
            directory / "kde_proxy_journal.json" for directory in journal_dirs
        )

        self.enabled = bool(self.kreadconfig_path and self.kwriteconfig_path)

    def _run(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            result = self._runner(
                argv,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise KdeProxyIntegrationError(
                f"Command failed to start: {argv[0]}: {exc}"
            ) from exc
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "unknown KConfig error").strip()
            raise KdeProxyIntegrationError(f"{Path(argv[0]).name}: {message}")
        return result

    def is_available(self) -> bool:
        return self.enabled

    def _existing_journal_paths(self) -> tuple[Path, ...]:
        return tuple(candidate for candidate in self._journal_candidates if candidate.is_file())

    def has_journal(self) -> bool:
        return bool(self._existing_journal_paths())

    def _read_key(self, key: str) -> dict[str, object]:
        if not self.kreadconfig_path:
            raise KdeProxyIntegrationError("kreadconfig is unavailable")
        result = self._run(
            [
                self.kreadconfig_path,
                "--file",
                CONFIG_FILE,
                "--group",
                CONFIG_GROUP,
                "--key",
                key,
                "--default",
                MISSING_SENTINEL,
            ]
        )
        value = result.stdout.rstrip("\r\n")
        if value == MISSING_SENTINEL:
            return {"present": False, "value": ""}
        return {"present": True, "value": value}

    def snapshot_current_state(self) -> dict[str, dict[str, object]]:
        return {key: self._read_key(key) for key in MANAGED_KEYS}

    def _supports_notify(self) -> bool:
        if self._notify_supported is not None:
            return self._notify_supported
        if not self.kwriteconfig_path:
            self._notify_supported = False
            return False
        try:
            result = self._runner(
                [self.kwriteconfig_path, "--help"],
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            self._notify_supported = False
            return False
        help_text = (result.stdout or "") + "\n" + (result.stderr or "")
        self._notify_supported = result.returncode == 0 and "--notify" in help_text
        return self._notify_supported

    def _write_key(self, key: str, value: str, *, notify: bool = False) -> None:
        if not self.kwriteconfig_path:
            raise KdeProxyIntegrationError("kwriteconfig is unavailable")
        argv = [
            self.kwriteconfig_path,
            "--file",
            CONFIG_FILE,
            "--group",
            CONFIG_GROUP,
            "--key",
            key,
        ]
        if key == "ReversedException":
            argv.extend(["--type", "bool"])
        if notify and self._supports_notify():
            argv.append("--notify")
        argv.append(value)
        self._run(argv)

    def _delete_key(self, key: str, *, notify: bool = False) -> None:
        if not self.kwriteconfig_path:
            raise KdeProxyIntegrationError("kwriteconfig is unavailable")
        argv = [
            self.kwriteconfig_path,
            "--file",
            CONFIG_FILE,
            "--group",
            CONFIG_GROUP,
            "--key",
            key,
            "--delete",
        ]
        if notify and self._supports_notify():
            argv.append("--notify")
        self._run(argv)

    def _atomic_write_journal(self, payload: Mapping[str, object]) -> None:
        journal_path = Path(self.journal_file)
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=".kde_proxy_",
            suffix=".tmp",
            dir=str(journal_path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, journal_path)
            directory_fd = os.open(journal_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def _load_journal(self) -> tuple[dict[str, object], Path]:
        paths = self._existing_journal_paths()
        if not paths:
            raise KdeProxyIntegrationError("KDE proxy recovery journal does not exist")
        if len(paths) > 1:
            locations = ", ".join(str(path) for path in paths)
            raise KdeProxyIntegrationError(
                "Multiple KDE proxy recovery journals were found; "
                f"automatic recovery is unsafe: {locations}"
            )
        path = paths[0]
        if path.stat().st_size > MAX_JOURNAL_BYTES:
            raise KdeProxyIntegrationError("KDE proxy recovery journal is too large")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise KdeProxyIntegrationError(
                f"Invalid KDE proxy recovery journal: {exc}"
            ) from exc
        if not isinstance(payload, dict) or payload.get("version") != JOURNAL_VERSION:
            raise KdeProxyIntegrationError("Unsupported KDE proxy recovery journal")
        if payload.get("state") != "applied" or not isinstance(payload.get("settings"), dict):
            raise KdeProxyIntegrationError("Malformed KDE proxy recovery journal")

        settings = payload["settings"]
        if set(settings) != set(MANAGED_KEYS):
            raise KdeProxyIntegrationError("Malformed KDE proxy settings snapshot")
        for key, entry in settings.items():
            if key not in MANAGED_KEYS or not isinstance(entry, dict):
                raise KdeProxyIntegrationError("Malformed KDE proxy setting entry")
            if set(entry) != {"present", "value"}:
                raise KdeProxyIntegrationError("Malformed KDE proxy setting entry")
            if not isinstance(entry["present"], bool) or not isinstance(entry["value"], str):
                raise KdeProxyIntegrationError("Malformed KDE proxy setting value")
        return payload, path

    def apply_proxy(self, port: int = 1080) -> bool:
        self.last_error = ""
        if not self.enabled:
            self.last_error = "KDE kreadconfig/kwriteconfig tools are unavailable"
            return False
        if not isinstance(port, int) or not (1 <= port <= 65535):
            self.last_error = "Invalid SOCKS proxy port"
            return False
        if self.has_journal():
            self.last_error = "Pending KDE proxy recovery must be completed first"
            return False

        try:
            snapshot = self.snapshot_current_state()
            payload = {
                "version": JOURNAL_VERSION,
                "state": "applied",
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "settings": snapshot,
                "applied": {"host": "127.0.0.1", "port": port},
            }
            self._atomic_write_journal(payload)

            # Configure endpoint keys first and switch ManualProxy on last.
            for key in ("httpProxy", "httpsProxy", "ftpProxy"):
                self._write_key(key, "")
            self._write_key("socksProxy", f"socks://127.0.0.1 {port}")
            self._write_key("ReversedException", "false")
            self._write_key("ProxyType", "1", notify=True)
            return True
        except KdeProxyIntegrationError as exc:
            apply_error = str(exc)
            rollback_ok = self.restore_proxy()
            if rollback_ok:
                self.last_error = apply_error + "; previous settings were restored"
            else:
                rollback_error = self.last_error
                self.last_error = apply_error + "; rollback failed: " + rollback_error
            return False

    def restore_proxy(self) -> bool:
        self.last_error = ""
        if not self.has_journal():
            return True
        if not self.kwriteconfig_path:
            self.last_error = "kwriteconfig is unavailable; recovery journal was retained"
            return False
        try:
            payload, journal_path = self._load_journal()
            settings = payload["settings"]
            assert isinstance(settings, dict)
            ordered_keys = [key for key in MANAGED_KEYS if key != "ProxyType"] + ["ProxyType"]
            for key in ordered_keys:
                entry = settings[key]
                assert isinstance(entry, dict)
                notify = key == "ProxyType"
                if entry["present"]:
                    self._write_key(key, str(entry["value"]), notify=notify)
                else:
                    self._delete_key(key, notify=notify)
            os.unlink(journal_path)
            return True
        except (OSError, KdeProxyIntegrationError) as exc:
            self.last_error = str(exc)
            return False

    def recover_if_needed(self) -> bool:
        return self.restore_proxy() if self.has_journal() else True
