import os
import tempfile
import json
import pytest
from unittest.mock import patch, MagicMock
from PySide6.QtWidgets import QApplication

# Initialize app for tests that need it (QSettings)
@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

def test_diagnostics():
    from src.diagnostics import DiagnosticsDialog
    
    dialog = DiagnosticsDialog()
    with patch("os.path.exists", return_value=True), \
         patch("os.access", return_value=True), \
         patch("shutil.which", return_value="/usr/bin/curl"), \
         patch("socket.socket") as mock_socket:
        
        # Test all pass
        assert dialog.run_diagnostics("/fake/ciadpi") == True
        
        # Test missing binary
        with patch("os.path.exists", return_value=False):
            assert dialog.run_diagnostics("/fake/ciadpi") == False
            
def test_gnome_proxy_adapter():
    from src.gnome_proxy import GnomeProxyAdapter
    
    with tempfile.TemporaryDirectory() as tmpdir:
        journal_file = os.path.join(tmpdir, "journal.json")
        
        with patch.object(GnomeProxyAdapter, "_check_gsettings", return_value=True), \
             patch("PySide6.QtCore.QStandardPaths.writableLocation", return_value=tmpdir), \
             patch("subprocess.run") as mock_run:
             
            # Create adapter
            adapter = GnomeProxyAdapter()
            adapter.journal_file = journal_file
            
            assert adapter.is_available() == True
            
            # Setup mock for _get_setting
            def mock_get_setting(*args, **kwargs):
                cmd = args[0]
                if cmd[0] == "gsettings" and cmd[1] == "get":
                    if cmd[3] == "mode": return MagicMock(returncode=0, stdout="'none'")
                    if cmd[3] == "host": return MagicMock(returncode=0, stdout="''")
                    if cmd[3] == "port": return MagicMock(returncode=0, stdout="0")
                return MagicMock(returncode=1)
                
            mock_run.side_effect = mock_get_setting
            
            # Test apply proxy
            adapter.apply_proxy(1080)
            
            # Check journal was created
            assert os.path.exists(journal_file)
            with open(journal_file, "r") as f:
                state = json.load(f)
                assert state["mode"] == "'none'"
                
            # Test restore
            adapter.restore_proxy()
            assert not os.path.exists(journal_file) # should be removed after restore

def test_install_scripts_dry_run():
    # We can't really run them safely without modifying ~/.local, 
    # but we can check if they are syntactically valid bash scripts.
    import subprocess
    
    res = subprocess.run(["bash", "-n", "scripts/install-user.sh"])
    assert res.returncode == 0
    
    res = subprocess.run(["bash", "-n", "scripts/uninstall-user.sh"])
    assert res.returncode == 0
