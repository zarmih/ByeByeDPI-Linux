#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from kde_proxy import KdeProxyAdapter, MANAGED_KEYS


class FakeKConfigRunner:
    def __init__(self) -> None:
        self.values = {
            "httpProxy": "http://old-proxy.example 3128",
            "httpsProxy": "http://old-proxy.example 3128",
            "ReversedException": "true",
            "ProxyType": "4",
        }
        self.calls: list[list[str]] = []
        self.fail_once_key: str | None = None

    def __call__(self, argv, **kwargs):
        assert isinstance(argv, list)
        assert kwargs.get("timeout") == 3
        self.calls.append(list(argv))
        key = argv[argv.index("--key") + 1]
        command = Path(argv[0]).name

        if command.startswith("kreadconfig"):
            default = argv[argv.index("--default") + 1]
            value = self.values.get(key, default)
            return subprocess.CompletedProcess(argv, 0, value + "\n", "")

        if not command.startswith("kwriteconfig"):
            raise AssertionError(argv)
        if self.fail_once_key == key:
            self.fail_once_key = None
            return subprocess.CompletedProcess(argv, 2, "", "simulated write failure")
        if "--delete" in argv:
            self.values.pop(key, None)
        else:
            self.values[key] = argv[-1]
        return subprocess.CompletedProcess(argv, 0, "", "")


def make_adapter(tmp: str, runner: FakeKConfigRunner) -> KdeProxyAdapter:
    return KdeProxyAdapter(
        runner=runner,
        data_dir=tmp,
        kreadconfig_path="kreadconfig6",
        kwriteconfig_path="kwriteconfig6",
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        runner = FakeKConfigRunner()
        original = dict(runner.values)
        adapter = make_adapter(tmp, runner)
        assert adapter.is_available()
        assert adapter.apply_proxy(1080), adapter.last_error
        assert runner.values["ProxyType"] == "1"
        assert runner.values["socksProxy"] == "socks://127.0.0.1 1080"
        assert runner.values["httpProxy"] == ""
        assert runner.values["httpsProxy"] == ""
        assert runner.values["ftpProxy"] == ""
        assert runner.values["ReversedException"] == "false"

        payload = json.loads(Path(adapter.journal_file).read_text(encoding="utf-8"))
        assert payload["version"] == 1
        assert payload["state"] == "applied"
        assert set(payload["settings"]) == set(MANAGED_KEYS)
        assert payload["settings"]["socksProxy"] == {"present": False, "value": ""}
        assert payload["settings"]["httpProxy"] == {
            "present": True,
            "value": original["httpProxy"],
        }

        assert adapter.restore_proxy(), adapter.last_error
        assert runner.values == original
        assert not Path(adapter.journal_file).exists()
        assert any("--delete" in call and "socksProxy" in call for call in runner.calls)
        assert any("--notify" in call and "ProxyType" in call for call in runner.calls)

    with tempfile.TemporaryDirectory() as tmp:
        runner = FakeKConfigRunner()
        adapter = make_adapter(tmp, runner)
        runner.fail_once_key = "ProxyType"
        assert not adapter.apply_proxy(1080)
        assert "previous settings were restored" in adapter.last_error
        assert not Path(adapter.journal_file).exists()

    with tempfile.TemporaryDirectory() as tmp:
        runner = FakeKConfigRunner()
        adapter = make_adapter(tmp, runner)
        assert not adapter.apply_proxy(0)
        assert "Invalid" in adapter.last_error
        assert runner.calls == []

    print("KDE proxy adapter smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
