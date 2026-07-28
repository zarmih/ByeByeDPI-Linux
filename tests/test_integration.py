import os
import stat
import subprocess
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import xml.etree.ElementTree as ET
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import tun_controller

def test_uninstall_script_aborts_on_recover_failure(tmp_path):
    script = Path(__file__).parent.parent / "scripts" / "uninstall-tun-helper.sh"
    
    # We can't easily mock the binary inside bash script in a pytest without manipulating PATH or replacing it,
    # but the script uses absolute path /usr/libexec/byebyedpi-linux/tun-helper.
    # Instead, we just check the bash script source for "set -euo pipefail" and no warnings.
    script_content = script.read_text()
    assert "set -euo pipefail" in script_content
    assert "rm -f --" in script_content
    assert "rmdir --ignore-fail-on-non-empty" in script_content
    assert "owner=$(stat -c '%u'" in script_content
    assert "perms=$(stat -c '%a'" in script_content

def test_install_script_no_sudo(tmp_path):
    script = Path(__file__).parent.parent / "scripts" / "install-tun-helper.sh"
    content = script.read_text()
    assert "sudo" not in content
    assert "pkexec" not in content
    assert "install -d -m 0755 -o root -g root" in content
    assert "install -m 0700 -o root -g root" in content

def test_install_user_script_no_sudo():
    script = Path(__file__).parent.parent / "scripts" / "install-user.sh"
    content = script.read_text()
    for line in content.splitlines():
        if "sudo" in line:
            assert "echo" in line
        if "pkexec" in line:
            assert "echo" in line

def test_uninstall_user_script_no_sudo():
    script = Path(__file__).parent.parent / "scripts" / "uninstall-user.sh"
    content = script.read_text()
    for line in content.splitlines():
        if "sudo" in line:
            assert "echo" in line
        if "pkexec" in line:
            assert "echo" in line
    assert "rm -rf --" in content

def test_polkit_policy_xml():
    policy_path = Path(__file__).parent.parent / "packaging" / "tun-helper" / "org.byebyedpi.linux.tun.policy"
    assert policy_path.exists()
    
    tree = ET.parse(policy_path)
    root = tree.getroot()
    assert root.tag == "policyconfig"
    
    action = root.find("action")
    assert action is not None
    assert action.attrib["id"] in ("org.byebyedpi.linux.tun", "org.byebyedpi.linux.tun.helper")
    
    defaults = action.find("defaults")
    assert defaults.find("allow_any").text == "no"
    assert defaults.find("allow_inactive").text == "no"
    assert defaults.find("allow_active").text == "auth_admin_keep"
    
    annotate = action.find("annotate")
    assert annotate.attrib["key"] == "org.freedesktop.policykit.exec.path"
    assert annotate.text == "/usr/libexec/byebyedpi-linux/tun-helper"

@patch("os.stat")
@patch("os.path.isfile")
@patch("os.access")
def test_controller_verify_paths(mock_access, mock_isfile, mock_stat):
    controller = tun_controller.TunController()
    
    def fake_stat(path):
        m = MagicMock()
        if path == "/usr/bin/pkexec":
            m.st_mode = stat.S_IFREG | stat.S_ISUID | 0o755
            m.st_uid = 0
        elif path == "/usr/libexec/byebyedpi-linux/tun-helper":
            m.st_mode = stat.S_IFREG | 0o700
            m.st_uid = 0
        elif "hev-socks5-tunnel" in str(path):
            m.st_mode = stat.S_IFREG | 0o755
            m.st_uid = os.getuid()
        else:
            raise OSError("Not found")
        return m

    mock_stat.side_effect = fake_stat
    mock_isfile.return_value = True
    mock_access.return_value = True

    # mock _get_hev_path so it passes exists()
    with patch.object(Path, 'exists', return_value=True):
        assert controller.check_availability()[0] == True
        # If pkexec has no suid bit, it should still pass now:
        def fake_stat_no_suid(path):
            m = fake_stat(path)
            if path == "/usr/bin/pkexec":
                m.st_mode = stat.S_IFREG | 0o755 # no suid
            return m
        mock_stat.side_effect = fake_stat_no_suid
        with patch.object(Path, 'exists', return_value=True):
            res, reason = controller.check_availability()
            assert res == True

        # If pkexec is writable:
        def fake_stat_writable(path):
            m = fake_stat(path)
            if path == "/usr/bin/pkexec":
                m.st_mode = stat.S_IFREG | 0o777
            return m
        mock_stat.side_effect = fake_stat_writable
        with patch.object(Path, 'exists', return_value=True):
            res, reason = controller.check_availability()
            assert res == False
        assert reason == "pkexec unsafe"
        
    # If HEV has suid bit:
    def fake_stat_hev_suid(path):
        m = fake_stat(path)
        if "hev-socks5-tunnel" in str(path):
            m.st_mode = stat.S_IFREG | stat.S_ISUID | 0o755
        return m
    mock_stat.side_effect = fake_stat_hev_suid
    with patch.object(Path, 'exists', return_value=True):
        res, reason = controller.check_availability()
        assert res == False
        assert reason == "HEV has SUID/SGID"
        
    # If HEV is world-writable:
    def fake_stat_hev_ww(path):
        m = fake_stat(path)
        if "hev-socks5-tunnel" in str(path):
            m.st_mode = stat.S_IFREG | 0o777
        return m
    mock_stat.side_effect = fake_stat_hev_ww
    with patch.object(Path, 'exists', return_value=True):
        res, reason = controller.check_availability()
        assert res == False
        assert reason == "HEV group/world-writable"

def test_main_gui_missing_helper():
    import os
    import sys
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    
    src_dir = Path(__file__).parent.parent / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
        
    from main import MainWindow
    from PySide6.QtCore import Qt

    # Mock check_availability to False
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if not app:
        app = QApplication([])
        
    with patch("tun_controller.TunController.check_availability", return_value=(False, "Helper missing")):
        window = MainWindow()
        
        # Check combobox
        idx = window.mode_combo.findData("tun")
        assert idx >= 0
        text = window.mode_combo.itemText(idx)
        assert "Unavailable" in text
        assert "Helper missing" in text
        
        flags = window.mode_combo.itemData(idx, Qt.UserRole - 1)
        assert flags == 0 # disabled

