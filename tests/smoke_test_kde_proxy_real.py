#!/usr/bin/env python3
"""Exercise KdeProxyAdapter against real KDE KConfig CLI tools in isolation."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from kde_proxy import KdeProxyAdapter


def run(argv: list[str]) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False)
    if result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {argv!r}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
    return result.stdout.rstrip("\r\n")


def find_tools() -> tuple[str, str]:
    for suffix in ("6", "5", ""):
        reader = shutil.which(f"kreadconfig{suffix}")
        writer = shutil.which(f"kwriteconfig{suffix}")
        if reader and writer:
            return reader, writer
    raise AssertionError("kreadconfig/kwriteconfig pair is not installed")


def read_key(reader: str, key: str, default: str = "__MISSING__") -> str:
    return run(
        [
            reader,
            "--file",
            "kioslaverc",
            "--group",
            "Proxy Settings",
            "--key",
            key,
            "--default",
            default,
        ]
    )


def write_key(writer: str, key: str, value: str, *, bool_value: bool = False) -> None:
    argv = [
        writer,
        "--file",
        "kioslaverc",
        "--group",
        "Proxy Settings",
        "--key",
        key,
    ]
    if bool_value:
        argv.extend(["--type", "bool"])
    argv.append(value)
    run(argv)


def main() -> int:
    reader, writer = find_tools()
    with tempfile.TemporaryDirectory(prefix="byebye-kconfig-") as tmp:
        root = Path(tmp)
        config_home = root / "config"
        data_home = root / "data"
        home = root / "home"
        for directory in (config_home, data_home, home):
            directory.mkdir(parents=True)

        old_env = {
            key: os.environ.get(key)
            for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "HOME")
        }
        os.environ["XDG_CONFIG_HOME"] = str(config_home)
        os.environ["XDG_DATA_HOME"] = str(data_home)
        os.environ["HOME"] = str(home)
        try:
            write_key(writer, "httpProxy", "http://old-proxy.example 3128")
            write_key(writer, "ProxyType", "4")
            write_key(writer, "ReversedException", "true", bool_value=True)
            assert (config_home / "kioslaverc").is_file()
            assert read_key(reader, "socksProxy") == "__MISSING__"

            adapter = KdeProxyAdapter(
                data_dir=root / "journal",
                kreadconfig_path=reader,
                kwriteconfig_path=writer,
            )
            assert adapter.apply_proxy(1080), adapter.last_error
            assert read_key(reader, "ProxyType") == "1"
            assert read_key(reader, "socksProxy") == "socks://127.0.0.1 1080"
            assert read_key(reader, "httpProxy") == ""
            assert read_key(reader, "ReversedException").lower() == "false"

            assert adapter.restore_proxy(), adapter.last_error
            assert read_key(reader, "httpProxy") == "http://old-proxy.example 3128"
            assert read_key(reader, "ProxyType") == "4"
            assert read_key(reader, "ReversedException").lower() == "true"
            assert read_key(reader, "socksProxy") == "__MISSING__"
            assert read_key(reader, "httpsProxy") == "__MISSING__"
            assert read_key(reader, "ftpProxy") == "__MISSING__"
            assert not Path(adapter.journal_file).exists()
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    print(
        "Real KDE KConfig smoke test passed using "
        f"{Path(reader).name}/{Path(writer).name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
