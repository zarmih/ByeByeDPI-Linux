import pytest
import os
import json
import subprocess
import sys
from unittest.mock import patch, MagicMock

import importlib.machinery
import importlib.util
helper_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../packaging/tun-helper/byebyedpi-tun-helper"))
loader = importlib.machinery.SourceFileLoader("tun_helper", helper_path)
spec = importlib.util.spec_from_loader("tun_helper", loader)
tun_helper = importlib.util.module_from_spec(spec)
sys.modules["tun_helper"] = tun_helper
loader.exec_module(tun_helper)

def create_journal(tmp_path, state="PREPARED", session_id="a"*32):
    journal_file = os.path.join(str(tmp_path), "journal.json")
    with open(journal_file, "w") as f:
        json.dump({
            "version": 1,
            "state": state,
            "plan": {
                "gateway_ip": "10.0.0.1",
                "physical_ip": "10.0.0.5",
                "connected_prefixes": ["10.0.0.0/24"]
            },
            "created_objects": [],
            "pending_operation": None,
            "owner_uid": 1000,
            "session_id": session_id,
            "controller_pid": 1234,
            "controller_starttime": 100
        }, f)
    return journal_file

@pytest.fixture
def watchdog_env(tmp_path):
    tun_helper.JOURNAL_DIR = str(tmp_path)
    tun_helper.JOURNAL_FILE = os.path.join(str(tmp_path), "journal.json")
    tun_helper.LOCK_FILE = os.path.join(str(tmp_path), "lock")
    create_journal(tmp_path)
    
    helper = tun_helper.TunHelper(
        runner=MagicMock(),
        sleep_fn=MagicMock(),
        watchdog_launcher=MagicMock(),
        _exit_fn=MagicMock(side_effect=Exception("Exit called"))
    )
    helper._ensure_dir = MagicMock()
    return helper, tmp_path

# 1. Alive and stable
def test_watchdog_alive_stable(watchdog_env):
    helper, tmp_path = watchdog_env
    helper.check_controller_alive = MagicMock(return_value=True)
    helper.probe_fn = MagicMock(return_value={"gateway_ip": "10.0.0.1", "physical_ip": "10.0.0.5", "connected_prefixes": ["10.0.0.0/24"]})
    helper.sleep_fn.side_effect = Exception("Stop loop") # to exit the infinite loop
    with patch('os.lstat') as mock_lstat:
        mock_st = MagicMock()
        mock_st.st_uid = 0
        mock_st.st_mode = 0o100600
        mock_st.st_size = 100
        mock_lstat.return_value = mock_st
        with pytest.raises(Exception, match="Stop loop"):
            helper._watchdog_loop(1234, 100, {"gateway_ip": "10.0.0.1", "physical_ip": "10.0.0.5", "connected_prefixes": ["10.0.0.0/24"]}, "a"*32)
    assert not helper._exit_fn.called

# 2. Death
def test_watchdog_death(watchdog_env):
    helper, tmp_path = watchdog_env
    helper.check_controller_alive = MagicMock(return_value=False)
    helper.rollback_internal = MagicMock()
    with patch('os.lstat') as mock_lstat:
        mock_st = MagicMock()
        mock_st.st_uid = 0
        mock_st.st_mode = 0o100600
        mock_st.st_size = 100
        mock_lstat.return_value = mock_st
        with patch('os.fstat') as mock_fstat:
            mock_fstat.return_value = mock_st
            with pytest.raises(Exception, match="Exit called"):
                helper._watchdog_loop(1234, 100, {"gateway_ip": "10.0.0.1", "physical_ip": "10.0.0.5", "connected_prefixes": ["10.0.0.0/24"]}, "a"*32)
    helper.rollback_internal.assert_called_once()
    helper._exit_fn.assert_called_once_with(0)

# 3. Gateway drift
def test_watchdog_gateway_drift(watchdog_env):
    helper, tmp_path = watchdog_env
    helper.check_controller_alive = MagicMock(return_value=True)
    helper.probe_fn = MagicMock(return_value={"gateway_ip": "10.0.0.2", "physical_ip": "10.0.0.5", "connected_prefixes": ["10.0.0.0/24"]})
    helper.rollback_internal = MagicMock()
    with patch('os.lstat') as mock_lstat, patch('os.fstat') as mock_fstat:
        mock_st = MagicMock()
        mock_st.st_uid = 0; mock_st.st_mode = 0o100600; mock_st.st_size = 100
        mock_lstat.return_value = mock_st; mock_fstat.return_value = mock_st
        with pytest.raises(Exception, match="Exit called"):
            helper._watchdog_loop(1234, 100, {"gateway_ip": "10.0.0.1", "physical_ip": "10.0.0.5", "connected_prefixes": ["10.0.0.0/24"]}, "a"*32)
    helper.rollback_internal.assert_called_once()

# 4. Source drift
def test_watchdog_source_drift(watchdog_env):
    helper, tmp_path = watchdog_env
    helper.check_controller_alive = MagicMock(return_value=True)
    helper.probe_fn = MagicMock(return_value={"gateway_ip": "10.0.0.1", "physical_ip": "192.168.1.5", "connected_prefixes": ["10.0.0.0/24"]})
    helper.rollback_internal = MagicMock()
    with patch('os.lstat') as mock_lstat, patch('os.fstat') as mock_fstat:
        mock_st = MagicMock(); mock_st.st_uid = 0; mock_st.st_mode = 0o100600; mock_st.st_size = 100
        mock_lstat.return_value = mock_st; mock_fstat.return_value = mock_st
        with pytest.raises(Exception, match="Exit called"):
            helper._watchdog_loop(1234, 100, {"gateway_ip": "10.0.0.1", "physical_ip": "10.0.0.5", "connected_prefixes": ["10.0.0.0/24"]}, "a"*32)
    helper.rollback_internal.assert_called_once()

# 5. Connected prefixes drift
def test_watchdog_prefixes_drift(watchdog_env):
    helper, tmp_path = watchdog_env
    helper.check_controller_alive = MagicMock(return_value=True)
    helper.probe_fn = MagicMock(return_value={"gateway_ip": "10.0.0.1", "physical_ip": "10.0.0.5", "connected_prefixes": ["10.0.0.0/24", "192.168.0.0/16"]})
    helper.rollback_internal = MagicMock()
    with patch('os.lstat') as mock_lstat, patch('os.fstat') as mock_fstat:
        mock_st = MagicMock(); mock_st.st_uid = 0; mock_st.st_mode = 0o100600; mock_st.st_size = 100
        mock_lstat.return_value = mock_st; mock_fstat.return_value = mock_st
        with pytest.raises(Exception, match="Exit called"):
            helper._watchdog_loop(1234, 100, {"gateway_ip": "10.0.0.1", "physical_ip": "10.0.0.5", "connected_prefixes": ["10.0.0.0/24"]}, "a"*32)
    helper.rollback_internal.assert_called_once()

# 6. Journal removed
def test_watchdog_journal_removed(watchdog_env):
    helper, tmp_path = watchdog_env
    helper.check_controller_alive = MagicMock(return_value=True)
    helper.probe_fn = MagicMock(return_value={"gateway_ip": "10.0.0.1", "physical_ip": "10.0.0.5", "connected_prefixes": ["10.0.0.0/24"]})
    helper.rollback_internal = MagicMock()
    os.remove(tun_helper.JOURNAL_FILE)
    with pytest.raises(Exception, match="Exit called"):
        helper._watchdog_loop(1234, 100, {"gateway_ip": "10.0.0.1", "physical_ip": "10.0.0.5", "connected_prefixes": ["10.0.0.0/24"]}, "a"*32)
    helper.rollback_internal.assert_not_called()
    helper._exit_fn.assert_called_once_with(0)

# 7. Session changed
def test_watchdog_session_changed(watchdog_env):
    helper, tmp_path = watchdog_env
    helper.check_controller_alive = MagicMock(return_value=True)
    helper.probe_fn = MagicMock(return_value={"gateway_ip": "10.0.0.1", "physical_ip": "10.0.0.5", "connected_prefixes": ["10.0.0.0/24"]})
    helper.rollback_internal = MagicMock()
    with patch('os.lstat') as mock_lstat:
        mock_st = MagicMock(); mock_st.st_uid = 0; mock_st.st_mode = 0o100600; mock_st.st_size = 100
        mock_lstat.return_value = mock_st
        with pytest.raises(Exception, match="Exit called"):
            helper._watchdog_loop(1234, 100, {"gateway_ip": "10.0.0.1", "physical_ip": "10.0.0.5", "connected_prefixes": ["10.0.0.0/24"]}, "b"*32)
    helper.rollback_internal.assert_not_called()
    helper._exit_fn.assert_called_once_with(0)

# 8. Concurrent rollback / State changed to ROLLING_BACK
def test_watchdog_state_changed(watchdog_env):
    helper, tmp_path = watchdog_env
    helper.check_controller_alive = MagicMock(return_value=True)
    helper.probe_fn = MagicMock(return_value={"gateway_ip": "10.0.0.1", "physical_ip": "10.0.0.5", "connected_prefixes": ["10.0.0.0/24"]})
    helper.rollback_internal = MagicMock()
    create_journal(tmp_path, state="ROLLING_BACK")
    with patch('os.lstat') as mock_lstat:
        mock_st = MagicMock(); mock_st.st_uid = 0; mock_st.st_mode = 0o100600; mock_st.st_size = 100
        mock_lstat.return_value = mock_st
        with pytest.raises(Exception, match="Exit called"):
            helper._watchdog_loop(1234, 100, {"gateway_ip": "10.0.0.1", "physical_ip": "10.0.0.5", "connected_prefixes": ["10.0.0.0/24"]}, "a"*32)
    helper.rollback_internal.assert_not_called()
    helper._exit_fn.assert_called_once_with(0)

