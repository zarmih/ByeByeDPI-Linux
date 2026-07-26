from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

import PySide6
from paths import user_config_dir, user_data_dir
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


class DiagnosticsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ByeByeDPI-Linux Diagnostics")
        self.resize(680, 500)

        layout = QVBoxLayout(self)
        self.info_label = QLabel("Diagnostics have not been run yet.")
        layout.addWidget(self.info_label)

        self.report_area = QTextEdit()
        self.report_area.setReadOnly(True)
        layout.addWidget(self.report_area)

        buttons = QHBoxLayout()
        self.copy_btn = QPushButton("Copy Report")
        self.copy_btn.clicked.connect(self.copy_report)
        buttons.addWidget(self.copy_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

    @staticmethod
    def _redact_path(value: str | os.PathLike[str]) -> str:
        text = str(value)
        home = str(Path.home())
        if text == home:
            return "~"
        if text.startswith(home + os.sep):
            return "~" + text[len(home):]
        return text

    @staticmethod
    def _writable_location(path: Path) -> bool:
        candidate = path
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
        return candidate.exists() and os.access(candidate, os.W_OK)

    def copy_report(self):
        QApplication.clipboard().setText(self.report_area.toPlainText())

    def run_diagnostics(self, binary_path: str, port: int = 1080) -> bool:
        binary = Path(binary_path)
        project_root = binary.parents[2]
        report: list[str] = ["--- ByeByeDPI-Linux Diagnostics ---"]
        failures = 0
        warnings = 0

        def add(level: str, message: str) -> None:
            nonlocal failures, warnings
            report.append(f"[{level}] {message}")
            if level == "FAIL":
                failures += 1
            elif level == "WARN":
                warnings += 1

        add("OK", f"PySide6 {PySide6.__version__}")

        if binary.is_file() and os.access(binary, os.X_OK):
            add("OK", f"ciadpi executable: {self._redact_path(binary)}")
        elif binary.exists():
            add("FAIL", f"ciadpi is not executable: {self._redact_path(binary)}")
        else:
            add("FAIL", f"ciadpi is missing: {self._redact_path(binary)}")

        vendor = project_root / "vendor" / "byedpi"
        if (vendor / "Makefile").is_file() and any(vendor.iterdir()):
            add("OK", "ByeDPI submodule files are present")
        else:
            add("FAIL", "ByeDPI submodule is missing or incomplete")

        curl = shutil.which("curl")
        add("OK" if curl else "FAIL", f"curl: {self._redact_path(curl) if curl else 'not found'}")

        required_build_tools = {
            "git": shutil.which("git"),
            "make": shutil.which("make"),
            "C compiler": shutil.which("cc") or shutil.which("gcc") or shutil.which("clang"),
        }
        for name, path in required_build_tools.items():
            add("OK" if path else "WARN", f"{name}: {self._redact_path(path) if path else 'not found'}")

        gsettings = shutil.which("gsettings")
        if gsettings:
            try:
                result = subprocess.run(
                    [gsettings, "get", "org.gnome.system.proxy", "mode"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                if result.returncode == 0:
                    add("OK", "GNOME gsettings proxy schema is readable")
                else:
                    add("WARN", "gsettings exists, but GNOME proxy schema is not readable")
            except (OSError, subprocess.SubprocessError) as exc:
                add("WARN", f"gsettings check failed: {exc}")
        else:
            add("WARN", "gsettings not found; optional GNOME SOCKS integration is disabled")

        if isinstance(port, int) and 1 <= port <= 65535:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.bind(("127.0.0.1", port))
                add("OK", f"Local port {port} is available")
            except OSError:
                add("WARN", f"Local port {port} is already in use")
        else:
            add("FAIL", f"Invalid local port: {port}")

        data_dir = user_data_dir(create=False)
        config_dir = user_config_dir(create=False)
        for label, directory in (("data directory", data_dir), ("config directory", config_dir)):
            if self._writable_location(directory):
                add("OK", f"Writable {label}: {self._redact_path(directory)}")
            else:
                add("FAIL", f"Not writable: {self._redact_path(directory)}")

        icon_path = project_root / "data" / "icon.png"
        if icon_path.is_file() and icon_path.stat().st_size >= 256:
            add("OK", f"Application icon is present ({icon_path.stat().st_size} bytes)")
        else:
            add("WARN", "Application icon is missing or only a placeholder")

        desktop_file = project_root / "data" / "byebyedpi.desktop"
        validator = shutil.which("desktop-file-validate")
        if desktop_file.is_file() and validator:
            try:
                result = subprocess.run(
                    [validator, str(desktop_file)],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                if result.returncode == 0:
                    add("OK", "Desktop file template is valid")
                else:
                    add("WARN", "Desktop file template needs regeneration by the installer")
            except (OSError, subprocess.SubprocessError) as exc:
                add("WARN", f"Desktop validation failed: {exc}")
        elif desktop_file.is_file():
            add("OK", "Desktop file template is present")
        else:
            add("WARN", "Desktop file template is missing")

        report.append(f"--- Summary: {failures} failure(s), {warnings} warning(s) ---")
        self.report_area.setPlainText("\n".join(report))
        if failures:
            self.info_label.setText("Some required checks failed.")
            self.info_label.setStyleSheet("color: red; font-weight: bold;")
        elif warnings:
            self.info_label.setText("Required checks passed with warnings.")
            self.info_label.setStyleSheet("color: darkorange; font-weight: bold;")
        else:
            self.info_label.setText("All checks passed.")
            self.info_label.setStyleSheet("color: green; font-weight: bold;")
        return failures == 0
