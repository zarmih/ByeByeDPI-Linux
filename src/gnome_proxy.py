from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Mapping

from PySide6.QtCore import QStandardPaths


APP_DATA_NAME = "ByeByeDPI-Linux"
JOURNAL_VERSION = 1
MAX_JOURNAL_BYTES = 1024 * 1024

PROXY_KEYS: dict[str, tuple[str, ...]] = {
    "org.gnome.system.proxy": (
        "mode",
        "autoconfig-url",
        "ignore-hosts",
        "use-same-proxy",
    ),
    "org.gnome.system.proxy.http": ("host", "port"),
    "org.gnome.system.proxy.https": ("host", "port"),
    "org.gnome.system.proxy.ftp": ("host", "port"),
    "org.gnome.system.proxy.socks": ("host", "port"),
}


class ProxyIntegrationError(RuntimeError):
    """Raised when GNOME proxy settings cannot be read or restored safely."""


Runner = Callable[..., subprocess.CompletedProcess[str]]


class GnomeProxyAdapter:
    """Optional, user-level GNOME SOCKS proxy integration with crash recovery.

    This adapter never requires root. It only invokes ``gsettings`` with argv
    lists. Tests can inject a runner and an explicit key map, so no real GNOME
    settings are changed during automated checks.
    """

    def __init__(
        self,
        *,
        runner: Runner | None = None,
        data_dir: str | os.PathLike[str] | None = None,
        gsettings_path: str | None = None,
        available_keys: Mapping[str, set[str]] | None = None,
    ) -> None:
        self._runner = runner or subprocess.run
        self.gsettings_path = gsettings_path or shutil.which("gsettings")
        self.last_error = ""

        app_dir = Path(data_dir) if data_dir is not None else self._default_data_dir()
        app_dir.mkdir(parents=True, exist_ok=True)
        self.journal_file = str(app_dir / "gnome_proxy_journal.json")

        self._available_keys = (
            {schema: set(keys) for schema, keys in available_keys.items()}
            if available_keys is not None
            else self._discover_available_keys()
        )
        required = self._available_keys.get("org.gnome.system.proxy.socks", set())
        root_keys = self._available_keys.get("org.gnome.system.proxy", set())
        self.enabled = bool(
            self.gsettings_path
            and {"host", "port"}.issubset(required)
            and "mode" in root_keys
        )

    @staticmethod
    def _default_data_dir() -> Path:
        base = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
        if base.name.casefold() != APP_DATA_NAME.casefold():
            base /= APP_DATA_NAME
        return base

    def _run(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            result = self._runner(
                argv,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProxyIntegrationError(f"Command failed to start: {argv[0]}: {exc}") from exc
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "unknown gsettings error").strip()
            raise ProxyIntegrationError(f"{' '.join(argv[:3])}: {message}")
        return result

    def _discover_available_keys(self) -> dict[str, set[str]]:
        if not self.gsettings_path:
            return {}
        try:
            schemas_result = self._run([self.gsettings_path, "list-schemas"])
            schemas = set(schemas_result.stdout.splitlines())
            discovered: dict[str, set[str]] = {}
            for schema in PROXY_KEYS:
                if schema not in schemas:
                    continue
                keys_result = self._run([self.gsettings_path, "list-keys", schema])
                discovered[schema] = set(keys_result.stdout.splitlines())
            return discovered
        except ProxyIntegrationError as exc:
            self.last_error = str(exc)
            return {}

    def is_available(self) -> bool:
        return self.enabled

    def has_journal(self) -> bool:
        return os.path.isfile(self.journal_file)

    def _iter_supported_settings(self):
        for schema, wanted_keys in PROXY_KEYS.items():
            available = self._available_keys.get(schema, set())
            for key in wanted_keys:
                if key in available:
                    yield schema, key

    def _get_setting(self, schema: str, key: str) -> str:
        if not self.gsettings_path:
            raise ProxyIntegrationError("gsettings is unavailable")
        result = self._run([self.gsettings_path, "get", schema, key])
        return result.stdout.strip()

    def _set_setting(self, schema: str, key: str, value: str) -> None:
        if not self.gsettings_path:
            raise ProxyIntegrationError("gsettings is unavailable")
        self._run([self.gsettings_path, "set", schema, key, value])

    def snapshot_current_state(self) -> dict[str, dict[str, str]]:
        snapshot: dict[str, dict[str, str]] = {}
        for schema, key in self._iter_supported_settings():
            snapshot.setdefault(schema, {})[key] = self._get_setting(schema, key)
        return snapshot

    def _atomic_write_journal(self, payload: dict) -> None:
        journal_path = Path(self.journal_file)
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=".gnome_proxy_",
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

    def _load_journal(self) -> dict:
        path = Path(self.journal_file)
        if not path.is_file():
            raise ProxyIntegrationError("GNOME proxy recovery journal does not exist")
        if path.stat().st_size > MAX_JOURNAL_BYTES:
            raise ProxyIntegrationError("GNOME proxy recovery journal is too large")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProxyIntegrationError(f"Invalid GNOME proxy recovery journal: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("version") != JOURNAL_VERSION:
            raise ProxyIntegrationError("Unsupported GNOME proxy recovery journal")
        if payload.get("state") != "applied" or not isinstance(payload.get("settings"), dict):
            raise ProxyIntegrationError("Malformed GNOME proxy recovery journal")
        for schema, values in payload["settings"].items():
            if schema not in PROXY_KEYS or not isinstance(values, dict):
                raise ProxyIntegrationError("Malformed GNOME proxy settings snapshot")
            for key, value in values.items():
                if key not in PROXY_KEYS[schema] or not isinstance(value, str):
                    raise ProxyIntegrationError("Malformed GNOME proxy setting value")
        return payload

    def apply_proxy(self, port: int = 1080) -> bool:
        self.last_error = ""
        if not self.enabled:
            self.last_error = self.last_error or "GNOME gsettings SOCKS proxy is unavailable"
            return False
        if not isinstance(port, int) or not (1 <= port <= 65535):
            self.last_error = "Invalid SOCKS proxy port"
            return False
        if self.has_journal():
            self.last_error = "Pending GNOME proxy recovery must be completed first"
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

            # Configure endpoints first and switch the global mode last.
            root_keys = self._available_keys.get("org.gnome.system.proxy", set())
            if "use-same-proxy" in root_keys:
                self._set_setting("org.gnome.system.proxy", "use-same-proxy", "false")
            for schema in (
                "org.gnome.system.proxy.http",
                "org.gnome.system.proxy.https",
                "org.gnome.system.proxy.ftp",
            ):
                keys = self._available_keys.get(schema, set())
                if "host" in keys:
                    self._set_setting(schema, "host", "''")
                if "port" in keys:
                    self._set_setting(schema, "port", "0")
            self._set_setting("org.gnome.system.proxy.socks", "host", "'127.0.0.1'")
            self._set_setting("org.gnome.system.proxy.socks", "port", str(port))
            self._set_setting("org.gnome.system.proxy", "mode", "'manual'")
            return True
        except ProxyIntegrationError as exc:
            apply_error = str(exc)
            # Best effort rollback; journal remains if any restoration step fails.
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
        if not self.gsettings_path:
            self.last_error = "gsettings is unavailable; recovery journal was retained"
            return False
        try:
            payload = self._load_journal()
            settings: dict[str, dict[str, str]] = payload["settings"]
            # Restore child schemas first, global mode last.
            ordered_schemas = [s for s in settings if s != "org.gnome.system.proxy"]
            if "org.gnome.system.proxy" in settings:
                ordered_schemas.append("org.gnome.system.proxy")
            for schema in ordered_schemas:
                items = list(settings[schema].items())
                if schema == "org.gnome.system.proxy":
                    items.sort(key=lambda item: item[0] == "mode")
                for key, value in items:
                    self._set_setting(schema, key, value)
            os.unlink(self.journal_file)
            return True
        except (OSError, ProxyIntegrationError) as exc:
            self.last_error = str(exc)
            return False

    def recover_if_needed(self) -> bool:
        return self.restore_proxy() if self.has_journal() else True
