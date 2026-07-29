import os
import json
import pytest
import shutil
import socket
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from diagnostics_core import run_diagnostics_core, redact_path, format_txt_report, check_writable
from diagnostics import DiagnosticsDialog
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

def test_redact_path(tmp_path):
    root = tmp_path / "project"
    home = str(Path.home())
    
    assert redact_path(root / "src" / "main.py", root) == "<PROJECT_ROOT>/src/main.py"
    assert redact_path(Path(home) / ".config" / "test", root) == "~/.config/test"

def test_check_writable(tmp_path):
    d = tmp_path / "test_dir"
    assert check_writable(d) == True
    
    # Create unwritable dir (if possible on this OS/user)
    # Just mock it for simplicity
    with patch("os.access", return_value=False):
        assert check_writable(d) == False

def test_diagnostics_core_all_pass(tmp_path):
    binary = tmp_path / "ciadpi"
    binary.touch(mode=0o755)
    
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    
    # Write empty strategies to avoid warnings
    with open(config_dir / "strategies.json", "w") as f:
        f.write("[]")
    
    with patch("shutil.which", return_value="/usr/bin/curl"), \
         patch("diagnostics_core.get_git_metadata", return_value={"branch": "master", "commit": "abc1234"}):
         
        report = run_diagnostics_core(str(binary), data_dir, config_dir, "6.5.0")
        
        assert report["schema_version"] == 1
        assert report["status"] == "PASS"
        assert report["failures"] == 0

def test_diagnostics_core_missing_binary(tmp_path):
    binary = tmp_path / "ciadpi"
    data_dir = tmp_path / "data"
    config_dir = tmp_path / "config"
    
    with patch("shutil.which", return_value=None):
        report = run_diagnostics_core(str(binary), data_dir, config_dir, "6.5.0")
        assert report["status"] == "FAIL"
        assert report["failures"] >= 1
        
        txt = format_txt_report(report)
        assert "Status: FAIL" in txt
        assert "[FAIL] ciadpi is missing" in txt
        assert "[WARN] curl not found" in txt

def test_diagnostics_gui_smoke(tmp_path):
    binary = tmp_path / "ciadpi"
    
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    
    with patch("diagnostics.run_diagnostics_core") as mock_core:
        mock_core.return_value = {
            "schema_version": 1,
            "timestamp": 12345678,
            "status": "PASS",
            "failures": 0,
            "warnings": 0,
            "results": [{"level": "PASS", "message": "All good", "action": ""}]
        }
        
        dialog = DiagnosticsDialog(str(binary))
        dialog.run_diagnostics()
        
        import time
        for _ in range(50):
            if dialog.last_report is not None:
                break
            app.processEvents()
            time.sleep(0.01)
            
        assert dialog.last_report is not None
        assert dialog.info_label.text() == "All checks passed."
        assert "All good" in dialog.report_area.toPlainText()
