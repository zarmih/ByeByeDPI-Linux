import os
import shutil
import socket
import subprocess
import tempfile
import json
import time
import sys
from pathlib import Path
from typing import Dict, Any, List

def redact_path(value: str | os.PathLike[str], project_root: Path) -> str:
    text = str(value)
    home = str(Path.home())
    temp_dir = tempfile.gettempdir()
    root_str = str(project_root)
    
    if text.startswith(root_str):
        text = "<PROJECT_ROOT>" + text[len(root_str):]
    elif text.startswith(temp_dir):
        text = "<TEMP_DIR>" + text[len(temp_dir):]
    elif text.startswith(home):
        text = "~" + text[len(home):]
    return text

def check_writable(directory: Path) -> bool:
    if not directory.exists():
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    if not directory.exists() or not os.access(directory, os.W_OK):
        return False
    try:
        fd, temp_path = tempfile.mkstemp(dir=directory)
        os.close(fd)
        os.remove(temp_path)
        return True
    except OSError:
        return False

def get_git_metadata(project_root: Path) -> Dict[str, str]:
    meta = {}
    git = shutil.which("git")
    if git and (project_root / ".git").exists():
        try:
            branch = subprocess.run([git, "rev-parse", "--abbrev-ref", "HEAD"], cwd=project_root, capture_output=True, text=True, timeout=1).stdout.strip()
            commit = subprocess.run([git, "rev-parse", "--short", "HEAD"], cwd=project_root, capture_output=True, text=True, timeout=1).stdout.strip()
            meta["branch"] = branch
            meta["commit"] = commit
        except (subprocess.SubprocessError, OSError):
            pass
    return meta

def run_diagnostics_core(binary_path: str, data_dir: Path, config_dir: Path, pyside_version: str) -> Dict[str, Any]:
    binary = Path(binary_path)
    project_root = binary.parents[2]
    
    results: List[Dict[str, str]] = []
    
    def add(level: str, msg: str, action: str = ""):
        results.append({"level": level, "message": msg, "action": action})

    add("PASS", f"Python {sys.version.split()[0]}", "")
    add("PASS", f"PySide6 {pyside_version}", "")

    # ciadpi
    if binary.is_file() and os.access(binary, os.X_OK):
        add("PASS", f"ciadpi executable: {redact_path(binary, project_root)}")
    elif binary.exists():
        add("FAIL", f"ciadpi is not executable: {redact_path(binary, project_root)}", "Make ciadpi executable (chmod +x)")
    else:
        add("FAIL", f"ciadpi is missing: {redact_path(binary, project_root)}", "Download or build ciadpi binary")

    # curl
    curl = shutil.which("curl")
    if curl:
        add("PASS", f"curl found: {redact_path(curl, project_root)}")
    else:
        add("WARN", "curl not found", "Install curl for update checking")

    # Writable dirs
    for label, d in [("data directory", data_dir), ("config directory", config_dir)]:
        if check_writable(d):
            add("PASS", f"Writable {label}: {redact_path(d, project_root)}")
        else:
            add("FAIL", f"Not writable {label}: {redact_path(d, project_root)}", "Check directory permissions")

    # Loopback bind
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
            add("PASS", f"Loopback bind available (tested on random port {port})")
    except OSError as e:
        add("FAIL", f"Loopback bind failed: {e}", "Check loopback interface configuration")

    # Autostart file
    autostart_file = Path.home() / ".config" / "autostart" / "byebyedpi.desktop"
    if autostart_file.exists():
        if os.access(autostart_file, os.R_OK):
            add("PASS", f"Autostart desktop file is readable: {redact_path(autostart_file, project_root)}")
        else:
            add("WARN", f"Autostart desktop file is not readable: {redact_path(autostart_file, project_root)}", "Check autostart file permissions")
    else:
        add("PASS", "Autostart desktop file not present (not enabled)")

    # Strategies and targets
    strategies_file = config_dir / "strategies.json"
    targets_file = config_dir / "targets.json"
    
    for label, f in [("Strategies", strategies_file), ("Targets", targets_file)]:
        if f.exists():
            try:
                with open(f, "r", encoding="utf-8") as file:
                    data = json.load(file)
                    count = len(data) if isinstance(data, (list, dict)) else 0
                    add("PASS", f"{label} file exists ({count} entries)")
            except Exception as e:
                add("WARN", f"Could not read {label} file: {e}", "Check file JSON format")
        else:
            add("PASS", f"{label} file not present (using defaults)")

    # Git metadata
    git_meta = get_git_metadata(project_root)
    if git_meta:
        add("PASS", f"Source metadata: branch {git_meta.get('branch')} commit {git_meta.get('commit')}")

    failures = sum(1 for r in results if r["level"] == "FAIL")
    warnings = sum(1 for r in results if r["level"] == "WARN")

    return {
        "schema_version": 1,
        "timestamp": int(time.time()),
        "status": "FAIL" if failures > 0 else ("WARN" if warnings > 0 else "PASS"),
        "failures": failures,
        "warnings": warnings,
        "results": results
    }

def format_txt_report(report: Dict[str, Any]) -> str:
    lines = [f"--- ByeByeDPI-Linux Diagnostics ---"]
    lines.append(f"Status: {report['status']} (Failures: {report['failures']}, Warnings: {report['warnings']})")
    lines.append(f"Timestamp: {report['timestamp']}")
    lines.append("-" * 40)
    for r in report["results"]:
        action = f" -> {r['action']}" if r.get("action") else ""
        lines.append(f"[{r['level']}] {r['message']}{action}")
    return "\n".join(lines)
