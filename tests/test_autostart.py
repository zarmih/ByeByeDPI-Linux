import pytest
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

import autostart_manager

@pytest.fixture
def mock_xdg_config():
    temp_dir = tempfile.mkdtemp()
    old_val = os.environ.get('XDG_CONFIG_HOME')
    os.environ['XDG_CONFIG_HOME'] = temp_dir
    yield temp_dir
    if old_val is not None:
        os.environ['XDG_CONFIG_HOME'] = old_val
    else:
        del os.environ['XDG_CONFIG_HOME']
    shutil.rmtree(temp_dir)

def test_autostart_enable_disable(mock_xdg_config):
    assert not autostart_manager.is_autostart_enabled()
    
    success, msg = autostart_manager.set_autostart(True, "/tmp/evil_script.sh")
    assert not success
    assert not autostart_manager.is_autostart_enabled()
    
    dummy_bin = os.path.join(mock_xdg_config, "byebyedpi-linux")
    with open(dummy_bin, 'w') as f:
        f.write("#!/bin/sh\\necho 1\\n")
    os.chmod(dummy_bin, 0o755)
    
    success, msg = autostart_manager.set_autostart(True, dummy_bin)
    assert success
    assert autostart_manager.is_autostart_enabled()
    
    autostart_file = autostart_manager.get_autostart_path()
    assert os.path.exists(autostart_file)
    with open(autostart_file, 'r') as f:
        content = f.read()
        assert "Exec=" + dummy_bin in content
        
    success, msg = autostart_manager.set_autostart(False)
    assert success
    assert not autostart_manager.is_autostart_enabled()
    assert not os.path.exists(autostart_file)

def test_autostart_symlink_protection(mock_xdg_config):
    dummy_bin = os.path.join(mock_xdg_config, "byebyedpi-linux")
    with open(dummy_bin, 'w') as f:
        f.write("test")
    os.chmod(dummy_bin, 0o755)
    
    autostart_file = autostart_manager.get_autostart_path()
    os.makedirs(os.path.dirname(autostart_file), exist_ok=True)
    
    # Create a malicious symlink
    target_file = os.path.join(mock_xdg_config, "sensitive_file")
    with open(target_file, 'w') as f:
        f.write("secret")
        
    os.symlink(target_file, autostart_file)
    
    # Now try to set autostart, it should replace the symlink, not write through it
    success, msg = autostart_manager.set_autostart(True, dummy_bin)
    assert success
    assert not os.path.islink(autostart_file)
    assert autostart_manager.is_autostart_enabled()
    
    with open(target_file, 'r') as f:
        assert f.read() == "secret" # original file is untouched
