import sys
import os
import json
import pytest
import stat
import fcntl
import importlib.util
from unittest.mock import patch, MagicMock
import subprocess

import importlib.machinery
import importlib.util
helper_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../packaging/tun-helper/byebyedpi-tun-helper"))
loader = importlib.machinery.SourceFileLoader("tun_helper", helper_path)
spec = importlib.util.spec_from_loader("tun_helper", loader)
tun_helper = importlib.util.module_from_spec(spec)
sys.modules["tun_helper"] = tun_helper
loader.exec_module(tun_helper)

@pytest.fixture
def mock_helper(tmp_path):
    tun_helper.JOURNAL_DIR = str(tmp_path)
    tun_helper.JOURNAL_FILE = os.path.join(str(tmp_path), "journal.json")
    tun_helper.LOCK_FILE = os.path.join(str(tmp_path), "lock")
    
    real_lstat = os.lstat
    real_fstat = os.fstat
    
    def fake_lstat(path, *args, **kwargs):
        st = real_lstat(path, *args, **kwargs)
        if str(path) in (tun_helper.JOURNAL_DIR, tun_helper.JOURNAL_FILE, tun_helper.LOCK_FILE):
            import stat
            mock_st = MagicMock()
            mock_st.st_uid = 0
            file_type = stat.S_IFMT(st.st_mode)
            if file_type == stat.S_IFDIR:
                mock_st.st_mode = stat.S_IFDIR | 0o700
            elif file_type == stat.S_IFREG:
                mock_st.st_mode = stat.S_IFREG | 0o600
            else:
                mock_st.st_mode = st.st_mode
            mock_st.st_size = st.st_size
            return mock_st
        return st

    def fake_fstat(fd, *args, **kwargs):
        st = real_fstat(fd, *args, **kwargs)
        import stat
        mock_st = MagicMock()
        mock_st.st_uid = 0
        file_type = stat.S_IFMT(st.st_mode)
        if file_type == stat.S_IFREG:
            mock_st.st_mode = stat.S_IFREG | 0o600
        else:
            mock_st.st_mode = st.st_mode
        mock_st.st_size = st.st_size
        mock_st.st_nlink = 1
        return mock_st

    with patch('os.lstat', side_effect=fake_lstat), \
         patch('os.fstat', side_effect=fake_fstat):
        runner = MagicMock()
        
        def runner_side_effect(*args, **kwargs):
            returncode = 1
            if not kwargs.get('check', True):
                res = MagicMock()
                res.returncode = 1
                res.stdout = "[]"
                return res
            return MagicMock()
        runner.side_effect = runner_side_effect
            
        helper = tun_helper.TunHelper(runner=runner)
        helper.watchdog_launcher = MagicMock()
        try:
            yield helper, runner
        finally:
            if getattr(helper, 'lock_fd', None) is not None:
                try:
                    fcntl.flock(helper.lock_fd, fcntl.LOCK_UN)
                    os.close(helper.lock_fd)
                except Exception:
                    pass
                helper.lock_fd = None

@pytest.fixture
def mock_pwd():
    with patch('pwd.getpwuid') as m:
        m.return_value = MagicMock(pw_name='testuser')
        yield m

def generate_valid_data():
    return {
        "owner_uid": 1000,
        "controller_pid": 1234,
        "controller_starttime": 5678,
        "session_id": "a" * 32,
        "plan": {
            "tun_interface": "byedpi0",
            "table_id": 10808,
            "tun_ip": "198.18.0.1",
            "physical_ip": "10.0.0.5",
            "gateway_ip": "10.0.0.1",
            "connected_prefixes": ["10.0.0.0/24"],
            "rule_priority_bypass_physical": 1000,
            "rule_priority_bypass_lan": 1100,
            "rule_priority_gateway": 1190,
            "rule_priority_catch_all": 2000
        }
    }

# 1-10: Config validations
def test_reject_invalid_plan_type(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    data["plan"] = "not_a_dict"
    with pytest.raises(tun_helper.TunHelperConfigError, match="Plan must be a dict"):
        helper.prepare(data, "1000")

def test_reject_missing_plan_keys(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    del data["plan"]["table_id"]
    with pytest.raises(tun_helper.TunHelperConfigError, match="Exact plan keys required"):
        helper.prepare(data, "1000")

def test_reject_invalid_interface(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    data["plan"]["tun_interface"] = "eth0"
    with pytest.raises(tun_helper.TunHelperConfigError, match="tun_interface must be byedpi0"):
        helper.prepare(data, "1000")

def test_reject_invalid_table(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    data["plan"]["table_id"] = 100
    with pytest.raises(tun_helper.TunHelperConfigError, match="table_id must be 10808"):
        helper.prepare(data, "1000")

def test_reject_invalid_ip(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    data["plan"]["tun_ip"] = "1.1.1.1"
    with pytest.raises(tun_helper.TunHelperConfigError, match="(Invalid |must be )"):
        helper.prepare(data, "1000")

def test_reject_shell_injection_ip(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    data["plan"]["physical_ip"] = "10.0.0.1; rm -rf /"
    with pytest.raises(tun_helper.TunHelperConfigError, match="Shell injection"):
        helper.prepare(data, "1000")

def test_reject_shell_injection_gateway(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    data["plan"]["gateway_ip"] = "10.0.0.1&"
    with pytest.raises(tun_helper.TunHelperConfigError, match="Shell injection"):
        helper.prepare(data, "1000")

def test_reject_shell_injection_tun_ip(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    data["plan"]["tun_ip"] = "10.0.0.1|"
    with pytest.raises(tun_helper.TunHelperConfigError, match="tun_ip must be"):
        helper.prepare(data, "1000")

def test_reject_shell_injection_prefix(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    data["plan"]["connected_prefixes"] = ["10.0.0.0/24; rm -rf /"]
    with pytest.raises(tun_helper.TunHelperConfigError, match="Shell injection"):
        helper.prepare(data, "1000")

def test_reject_duplicate_prefixes(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    data["plan"]["connected_prefixes"] = ["10.0.0.0/24", "10.0.0.0/24"]
    with pytest.raises(tun_helper.TunHelperConfigError, match="Duplicate"):
        helper.prepare(data, "1000")

# 11-20
def test_reject_overlong_prefixes(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    data["plan"]["connected_prefixes"] = [f"10.0.{i}.0/24" for i in range(70)]
    with pytest.raises(tun_helper.TunHelperConfigError, match="max 64"):
        helper.prepare(data, "1000")

def test_reject_wrong_priority_physical(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    data["plan"]["rule_priority_bypass_physical"] = 999
    with pytest.raises(tun_helper.TunHelperConfigError, match="bypass_physical must be 1000"):
        helper.prepare(data, "1000")

def test_reject_wrong_priority_lan(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    data["plan"]["rule_priority_bypass_lan"] = 999
    with pytest.raises(tun_helper.TunHelperConfigError, match="bypass_lan must be 1100"):
        helper.prepare(data, "1000")

def test_reject_wrong_priority_gateway(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    data["plan"]["rule_priority_gateway"] = 999
    with pytest.raises(tun_helper.TunHelperConfigError, match="bypass_gateway must be 1190"):
        helper.prepare(data, "1000")

def test_reject_wrong_priority_catch_all(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    data["plan"]["rule_priority_catch_all"] = 999
    with pytest.raises(tun_helper.TunHelperConfigError, match="catch_all must be 2000"):
        helper.prepare(data, "1000")

def test_reject_invalid_uid(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    data["owner_uid"] = 0
    with pytest.raises(tun_helper.TunHelperConfigError, match="must be non-zero"):
        helper.prepare(data, "1000")

def test_reject_pkexec_uid_mismatch(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    with pytest.raises(tun_helper.TunHelperSecurityError, match="mismatch"):
        helper.prepare(data, "1001")

def test_reject_nonexistent_uid(mock_pwd, mock_helper):
    mock_pwd.side_effect = KeyError
    helper, _ = mock_helper
    data = generate_valid_data()
    with pytest.raises(tun_helper.TunHelperConfigError, match="does not exist"):
        helper.prepare(data, "1000")

def test_reject_invalid_pid(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    data["controller_pid"] = -1
    with pytest.raises(tun_helper.TunHelperConfigError, match="Invalid controller_pid"):
        helper.validate_request(data, "1000")

def test_reject_invalid_starttime(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    data["controller_starttime"] = -1
    with pytest.raises(tun_helper.TunHelperConfigError, match="Invalid controller_starttime"):
        helper.validate_request(data, "1000")

# 21-30
def test_reject_invalid_session_id(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    data["session_id"] = "a" * 31
    with pytest.raises(tun_helper.TunHelperConfigError, match="Invalid session_id format"):
        helper.validate_request(data, "1000")

def test_dir_symlink_rejected(mock_helper, tmp_path):
    helper, _ = mock_helper
    helper = tun_helper.TunHelper(runner=MagicMock())
    os.rmdir(tun_helper.JOURNAL_DIR)
    os.symlink("/tmp", tun_helper.JOURNAL_DIR)
    with pytest.raises(tun_helper.TunHelperSecurityError, match="Unsafe directory"):
        helper._ensure_dir()
    os.unlink(tun_helper.JOURNAL_DIR)

def test_dir_wrong_owner_rejected(mock_helper, tmp_path):
    helper, _ = mock_helper
    helper = tun_helper.TunHelper(runner=MagicMock())
    with patch('os.lstat') as mock_lstat:
        st = MagicMock()
        st.st_uid = 1000
        st.st_mode = stat.S_IFDIR | 0o700
        mock_lstat.return_value = st
        with pytest.raises(tun_helper.TunHelperSecurityError, match="Unsafe directory"):
            helper._ensure_dir()

def test_lock_symlink_rejected(mock_helper):
    helper, _ = mock_helper
    with patch('os.fstat') as mock_fstat:
        st = MagicMock()
        st.st_uid = 0
        st.st_mode = stat.S_IFLNK | 0o600
        mock_fstat.return_value = st
        with pytest.raises(tun_helper.TunHelperError, match="Unsafe lock file"):
            helper.acquire_lock()

def test_journal_symlink_rejected(mock_helper):
    helper, _ = mock_helper
    with open(tun_helper.JOURNAL_FILE, "w") as f: f.write("{}")
    with patch('os.lstat') as mock_lstat:
        st = MagicMock()
        st.st_uid = 0
        st.st_mode = stat.S_IFLNK | 0o600
        mock_lstat.return_value = st
        with pytest.raises(tun_helper.TunHelperSecurityError, match="Unsafe journal"):
            helper.read_journal()

def test_journal_wrong_owner(mock_helper):
    helper, _ = mock_helper
    with open(tun_helper.JOURNAL_FILE, "w") as f: f.write("{}")
    with patch('os.lstat') as mock_lstat:
        st = MagicMock()
        st.st_uid = 1000
        st.st_mode = stat.S_IFREG | 0o600
        mock_lstat.return_value = st
        with pytest.raises(tun_helper.TunHelperSecurityError, match="Unsafe journal"):
            helper.read_journal()

def test_journal_too_large(mock_helper):
    helper, _ = mock_helper
    with open(tun_helper.JOURNAL_FILE, "w") as f: f.write("{}")
    with patch('os.lstat') as mock_lstat:
        st = MagicMock()
        st.st_uid = 0
        st.st_mode = stat.S_IFREG | 0o600
        st.st_size = 70000
        mock_lstat.return_value = st
        with pytest.raises(tun_helper.TunHelperSecurityError, match="empty or too large"):
            helper.read_journal()

def test_journal_empty(mock_helper):
    helper, _ = mock_helper
    with open(tun_helper.JOURNAL_FILE, "w") as f: pass
    with pytest.raises(tun_helper.TunHelperSecurityError, match="empty or too large"):
        helper.read_journal()

def test_journal_invalid_json(mock_helper):
    helper, _ = mock_helper
    with open(tun_helper.JOURNAL_FILE, "w") as f: f.write("{invalid")
    with pytest.raises(tun_helper.TunHelperSecurityError, match="invalid JSON"):
        helper.read_journal()

def test_journal_wrong_version(mock_helper):
    helper, _ = mock_helper
    with open(tun_helper.JOURNAL_FILE, "w") as f: json.dump({"version": 2}, f)
    with pytest.raises(tun_helper.TunHelperSecurityError, match="Invalid journal version"):
        helper.read_journal()

# 31-40
def test_journal_invalid_state(mock_helper):
    helper, _ = mock_helper
    with open(tun_helper.JOURNAL_FILE, "w") as f: json.dump({"version": 1, "state": "BAD"}, f)
    with pytest.raises(tun_helper.TunHelperSecurityError, match="Invalid state"):
        helper.read_journal()

def test_journal_missing_pending(mock_helper):
    helper, _ = mock_helper
    with open(tun_helper.JOURNAL_FILE, "w") as f: json.dump({
        "version": 1, "state": "PREPARING", "plan": {}, "created_objects": []
    }, f)
    with pytest.raises(tun_helper.TunHelperSecurityError, match="Missing pending_operation"):
        helper.read_journal()

def test_journal_invalid_embedded_plan(mock_helper):
    helper, _ = mock_helper
    with open(tun_helper.JOURNAL_FILE, "w") as f: json.dump({
        "version": 1, "state": "PREPARING", "plan": "str", "created_objects": [], "pending_operation": None
    }, f)
    with pytest.raises(tun_helper.TunHelperSecurityError, match="Invalid plan or created_objects"):
        helper.read_journal()

def test_journal_not_dict(mock_helper):
    helper, _ = mock_helper
    with open(tun_helper.JOURNAL_FILE, "w") as f: json.dump([], f)
    with pytest.raises(tun_helper.TunHelperSecurityError, match="Journal must be a dict"):
        helper.read_journal()

def test_prepare_success(mock_pwd, mock_helper):
    helper, runner = mock_helper
    data = generate_valid_data()
    
    with patch.object(helper, 'check_controller_alive', return_value=True), \
         patch('os.fork', return_value=123), \
         patch('os.waitpid'):
         
        def side_effect(*args, **kwargs):
            if not kwargs.get('check', True):
                res = MagicMock()
                res.returncode = 1
                res.stdout = "[]"
                return res
            return MagicMock()
        runner.side_effect = side_effect
        
        helper.prepare(data, "1000")
        j = helper.read_journal()
        assert j["state"] == "PREPARED"
        assert len(j["created_objects"]) == 6

def test_prepare_conflict_link(mock_pwd, mock_helper):
    helper, runner = mock_helper
    data = generate_valid_data()
    
    with patch.object(helper, 'check_controller_alive', return_value=True):
        def side_effect(*args, **kwargs):
            res = MagicMock()
            res.returncode = 0 if "link" in args[0] else 1
            res.stdout = "[]"
            return res
        runner.side_effect = side_effect
        
        with pytest.raises(tun_helper.TunHelperError, match="Interface byedpi0 already exists"):
            helper.prepare(data, "1000")

def test_prepare_conflict_rule(mock_pwd, mock_helper):
    helper, runner = mock_helper
    data = generate_valid_data()
    
    with patch.object(helper, 'check_controller_alive', return_value=True):
        def side_effect(*args, **kwargs):
            res = MagicMock()
            if "rule" in args[0]:
                res.returncode = 0
                res.stdout = '[{"priority": 1500, "table": "main"}]'
            else:
                res.returncode = 1
            return res
        runner.side_effect = side_effect
        
        with pytest.raises(tun_helper.TunHelperError, match="Conflicting rule"):
            helper.prepare(data, "1000")

def test_activate_without_prepare(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    with pytest.raises(tun_helper.TunHelperConfigError, match="Not in PREPARED state"):
        helper.activate(data, "1000")

def test_activate_auth_failure(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    with open(tun_helper.JOURNAL_FILE, "w") as f: json.dump({
        "version": 1, "state": "PREPARED", "plan": data["plan"], "created_objects": [], "pending_operation": None,
        "owner_uid": 1000, "session_id": "b"*32, "controller_pid": 1, "controller_starttime": 1
    }, f)
    with pytest.raises(tun_helper.TunHelperSecurityError, match="Authorization failed"):
        helper.activate(data, "1000")

def test_activate_success(mock_helper):
    helper, runner = mock_helper
    data = generate_valid_data()
    with open(tun_helper.JOURNAL_FILE, "w") as f: json.dump({
        "version": 1, "state": "PREPARED", "plan": data["plan"], "created_objects": [{"type": "link", "dev": "byedpi0"}], "pending_operation": None,
        "owner_uid": 1000, "session_id": data["session_id"], "controller_pid": 1, "controller_starttime": 1
    }, f)
    helper.activate(data, "1000")
    j = helper.read_journal()
    assert j["state"] == "ACTIVE"
    assert len(j["created_objects"]) == 3

# 41-50
def test_rollback_auth_failure(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    with open(tun_helper.JOURNAL_FILE, "w") as f: json.dump({
        "version": 1, "state": "ACTIVE", "plan": data["plan"], "created_objects": [], "pending_operation": None,
        "owner_uid": 1000, "session_id": "b"*32, "controller_pid": 1, "controller_starttime": 1
    }, f)
    with pytest.raises(tun_helper.TunHelperSecurityError, match="Authorization failed"):
        helper.rollback(data, "1000", is_recover=False)

def test_recover_auth_success(mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    with open(tun_helper.JOURNAL_FILE, "w") as f: json.dump({
        "version": 1, "state": "ACTIVE", "plan": data["plan"], "created_objects": [], "pending_operation": None,
        "owner_uid": 1000, "session_id": "b"*32, "controller_pid": 1, "controller_starttime": 1
    }, f)
    with patch.object(helper, 'rollback_internal') as m:
        helper.rollback(data, "1000", is_recover=True)
        m.assert_called_once()

def test_rollback_internal_success(mock_helper):
    helper, runner = mock_helper
    data = generate_valid_data()
    with open(tun_helper.JOURNAL_FILE, "w") as f: json.dump({
        "version": 1, "state": "ACTIVE", "plan": data["plan"], 
        "created_objects": [{"type": "link", "dev": "byedpi0"}], "pending_operation": None,
        "owner_uid": 1000, "session_id": "a"*32, "controller_pid": 1, "controller_starttime": 1
    }, f)
    
    def side_effect(*args, **kwargs):
        res = MagicMock()
        res.returncode = 1 # verify fails -> absent -> success deletion
        res.stdout = "[]"
        return res
    runner.side_effect = side_effect
    
    helper.rollback_internal()
    assert not os.path.exists(tun_helper.JOURNAL_FILE)

def test_rollback_internal_failed(mock_helper):
    helper, runner = mock_helper
    data = generate_valid_data()
    with open(tun_helper.JOURNAL_FILE, "w") as f: json.dump({
        "version": 1, "state": "ACTIVE", "plan": data["plan"], 
        "created_objects": [{"type": "link", "dev": "byedpi0"}], "pending_operation": None,
        "owner_uid": 1000, "session_id": "a"*32, "controller_pid": 1, "controller_starttime": 1
    }, f)
    
    def side_effect(*args, **kwargs):
        res = MagicMock()
        res.returncode = 0 # exists! -> deletion failed
        res.stdout = '[{"test": "data"}]'
        return res
    runner.side_effect = side_effect
    
    with pytest.raises(tun_helper.TunHelperError, match="Rollback incomplete or failed"):
        helper.rollback_internal()
    
    j = helper.read_journal()
    assert j["state"] == "ROLLBACK_FAILED"

def test_rollback_pending_op(mock_helper):
    helper, runner = mock_helper
    data = generate_valid_data()
    with open(tun_helper.JOURNAL_FILE, "w") as f: json.dump({
        "version": 1, "state": "PREPARING", "plan": data["plan"], 
        "created_objects": [], "pending_operation": {"type": "link", "dev": "byedpi0"},
        "owner_uid": 1000, "session_id": "a"*32, "controller_pid": 1, "controller_starttime": 1
    }, f)
    
    def side_effect(*args, **kwargs):
        res = MagicMock()
        res.returncode = 1 # not exists -> deleted
        res.stdout = '[]'
        return res
    runner.side_effect = side_effect
    
    helper.rollback_internal()
    assert not os.path.exists(tun_helper.JOURNAL_FILE)

def test_crash_during_mutation(mock_pwd, mock_helper):
    helper, runner = mock_helper
    data = generate_valid_data()
    
    with patch.object(helper, 'check_controller_alive', return_value=True), \
         patch('os.fork', return_value=123), \
         patch('os.waitpid'):
         
        def side_effect(*args, **kwargs):
            if not kwargs.get('check', True):
                res = MagicMock()
                res.returncode = 1
                res.stdout = "[]"
                return res
            raise subprocess.CalledProcessError(1, [])
        runner.side_effect = side_effect
        
        with patch.object(helper, 'rollback_internal') as m_rollback:
            with pytest.raises(tun_helper.TunHelperError):
                helper.prepare(data, "1000")
            m_rollback.assert_called_once()
            j = helper.read_journal()
            assert j["pending_operation"] is not None

def test_status_output(mock_helper, capsys):
    helper, _ = mock_helper
    data = generate_valid_data()
    with open(tun_helper.JOURNAL_FILE, "w") as f: json.dump({
        "version": 1, "state": "ACTIVE", "plan": data["plan"], "created_objects": [], "pending_operation": None,
        "owner_uid": 1000, "session_id": data["session_id"], "controller_pid": 1, "controller_starttime": 1
    }, f)
    helper.status(data, "1000")
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert out["state"] == "ACTIVE"
    assert out["session_owned"] is True

def test_delete_journal_unsafe(mock_helper):
    helper, _ = mock_helper
    with open(tun_helper.JOURNAL_FILE, "w") as f: f.write("{}")
    with patch('os.lstat') as mock_lstat:
        st = MagicMock()
        st.st_uid = 1000
        st.st_mode = stat.S_IFLNK | 0o600
        mock_lstat.return_value = st
        with pytest.raises(tun_helper.TunHelperSecurityError, match="Unsafe journal file"):
            helper.delete_journal()

def test_rollback_order(mock_helper):
    helper, runner = mock_helper
    data = generate_valid_data()
    with open(tun_helper.JOURNAL_FILE, "w") as f: json.dump({
        "version": 1, "state": "ACTIVE", "plan": data["plan"], 
        "created_objects": [
            {"type": "link", "dev": "byedpi0"},
            {"type": "route", "dest": "default", "dev": "byedpi0", "table": 10808},
            {"type": "rule", "from": "all", "lookup": 10808, "priority": 2000},
            {"type": "addr", "ip": "1.1.1.1", "dev": "byedpi0"}
        ], "pending_operation": None,
        "owner_uid": 1000, "session_id": "a"*32, "controller_pid": 1, "controller_starttime": 1
    }, f)
    
    cmds_run = []
    def side_effect(*args, **kwargs):
        cmds_run.append(args[0])
        res = MagicMock()
        res.returncode = 1 # always absent
        res.stdout = "[]"
        return res
    runner.side_effect = side_effect
    
    helper.rollback_internal()
    assert cmds_run[0][-1] == "2000" # rule catch-all first
    assert cmds_run[2][-2] == "table" # route next
    assert cmds_run[4][-1] == "byedpi0" # link last (approx order checks)

def test_rollback_idempotent(mock_helper):
    helper, runner = mock_helper
    data = generate_valid_data()
    with open(tun_helper.JOURNAL_FILE, "w") as f: json.dump({
        "version": 1, "state": "ACTIVE", "plan": data["plan"], 
        "created_objects": [{"type": "link", "dev": "byedpi0"}], "pending_operation": None,
        "owner_uid": 1000, "session_id": "a"*32, "controller_pid": 1, "controller_starttime": 1
    }, f)
    
    def side_effect(*args, **kwargs):
        res = MagicMock()
        res.returncode = 1
        return res
    runner.side_effect = side_effect
    
    helper.rollback_internal()
    helper.rollback_internal() # Second time, should not crash, file absent
    assert not os.path.exists(tun_helper.JOURNAL_FILE)

# 51
def test_prepare_already_active(mock_pwd, mock_helper):
    helper, _ = mock_helper
    data = generate_valid_data()
    with open(tun_helper.JOURNAL_FILE, "w") as f: json.dump({
        "version": 1, "state": "ACTIVE", "plan": data["plan"], "created_objects": [], "pending_operation": None,
        "owner_uid": 1000, "session_id": "a"*32, "controller_pid": 1, "controller_starttime": 1
    }, f)
    with patch.object(helper, 'check_controller_alive', return_value=True):
        with pytest.raises(tun_helper.TunHelperConfigError, match="already active or prepared"):
            helper.prepare(data, "1000")
