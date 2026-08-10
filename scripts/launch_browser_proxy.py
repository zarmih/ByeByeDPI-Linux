#!/usr/bin/env python3
"""Launch a Chromium-family browser through the local ByeByeDPI SOCKS5 proxy."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence

BROWSER_CANDIDATES = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "brave-browser",
    "brave",
    "ungoogled-chromium",
)


def validate_port(value: str | int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def resolve_browser(explicit: str | None = None) -> str:
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.parent != Path("."):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate.resolve())
            raise FileNotFoundError(f"browser executable is not usable: {candidate}")
        resolved = shutil.which(explicit)
        if resolved:
            return resolved
        raise FileNotFoundError(f"browser command was not found: {explicit}")

    for name in BROWSER_CANDIDATES:
        resolved = shutil.which(name)
        if resolved:
            return resolved
    raise FileNotFoundError(
        "no supported Chromium-family browser found; use --browser /path/to/executable"
    )


def default_profile_dir(
    browser: str,
    port: int,
    env: Mapping[str, str] | None = None,
) -> Path:
    environment = os.environ if env is None else env
    cache_root = Path(
        environment.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
    ).expanduser()
    browser_name = Path(browser).name.replace("/", "_")
    return cache_root / "byebyedpi-linux" / "browser-profiles" / f"{browser_name}-{port}"


def build_command(
    browser: str,
    port: int,
    profile_dir: Path,
    url: str | None = None,
) -> list[str]:
    command = [
        browser,
        f"--proxy-server=socks5://127.0.0.1:{port}",
        "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1",
        f"--user-data-dir={profile_dir}",
    ]
    if url:
        command.append(url)
    return command


def proxy_is_reachable(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch Chromium through the local ByeByeDPI SOCKS5 proxy."
    )
    parser.add_argument("--port", type=validate_port, default=1080)
    parser.add_argument(
        "--browser",
        help="Browser command or executable path; auto-detected when omitted.",
    )
    parser.add_argument("--url", help="Optional URL to open.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the command without checking the proxy or launching a browser.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        browser = resolve_browser(args.browser)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    profile_dir = default_profile_dir(browser, args.port)
    command = build_command(browser, args.port, profile_dir, args.url)

    if args.dry_run:
        print(shlex.join(command))
        return 0

    if not proxy_is_reachable(args.port):
        print(
            f"Error: no local SOCKS proxy is listening on 127.0.0.1:{args.port}. "
            "Start ByeByeDPI first.",
            file=sys.stderr,
        )
        return 3

    profile_dir.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(command, start_new_session=True)  # noqa: S603
    print(
        f"Started {Path(browser).name} (pid {process.pid}) through "
        f"socks5://127.0.0.1:{args.port}"
    )
    print(f"Dedicated browser profile: {profile_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
