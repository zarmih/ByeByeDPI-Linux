#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "launch_browser_proxy.py"
spec = importlib.util.spec_from_file_location("launch_browser_proxy", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def main() -> int:
    assert module.validate_port("1080") == 1080
    for bad in ("0", "65536", "nope"):
        try:
            module.validate_port(bad)
        except argparse.ArgumentTypeError:
            pass
        else:
            raise AssertionError(f"invalid port accepted: {bad}")

    with tempfile.TemporaryDirectory() as tmp:
        env = {"XDG_CACHE_HOME": tmp}
        profile = module.default_profile_dir("/usr/bin/chromium", 1080, env)
        assert profile == Path(tmp) / "byebyedpi-linux/browser-profiles/chromium-1080"
        command = module.build_command(
            "/usr/bin/chromium", 1080, profile, "https://example.com/"
        )
        assert command[0] == "/usr/bin/chromium"
        assert "--proxy-server=socks5://127.0.0.1:1080" in command
        assert "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1" in command
        assert any(item.startswith("--user-data-dir=") for item in command)
        assert command[-1] == "https://example.com/"

    assert module.proxy_is_reachable(1, timeout=0.01) is False
    print("Browser proxy helper smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
