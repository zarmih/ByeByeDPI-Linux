import pytest
from unittest.mock import MagicMock, patch
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import tun_plan
from tun_controller import TunController, TunControllerError, TunRollbackError

def test_tun_controller_order_and_readiness():
    controller = TunController()
    controller.check_handshake = MagicMock(return_value=True)
    controller._call_helper = MagicMock()
    controller._generate_hev_config = MagicMock(return_value="/tmp/fake_config.yml")
    controller._get_hev_path = MagicMock(return_value=Path("/tmp/fake_hev"))
    controller.get_controller_starttime = MagicMock(return_value=123)

    plan = tun_plan.TunPlan(
        table_id=10808,
        tun_interface="tun0",
        tun_ip="10.0.0.2",
        physical_interface="eth0",
        physical_ip="192.168.1.5",
        gateway_ip="192.168.1.1",
        connected_prefixes=[],
        rule_priority_bypass_physical=10,
        rule_priority_bypass_lan=11,
        rule_priority_gateway=12,
        rule_priority_catch_all=13
    )

    with patch("subprocess.Popen") as mock_popen, patch("subprocess.run") as mock_run, patch("time.sleep"):
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        
        # Mock readiness loop to succeed on second iteration
        run_res_fail = MagicMock()
        run_res_fail.returncode = 1
        run_res_success = MagicMock()
        run_res_success.returncode = 0
        mock_run.side_effect = [run_res_fail, run_res_success]

        controller.start(plan)

        # Ensure order: prepare -> Popen (hev start unprivileged) -> activate
        assert controller._call_helper.call_count == 2
        controller._call_helper.assert_any_call("prepare", {
            "plan": {
                "tun_interface": "tun0",
                "tun_ip": "10.0.0.2",
                "physical_ip": "192.168.1.5",
                "gateway_ip": "192.168.1.1",
                "connected_prefixes": [],
                "rule_priority_bypass_physical": 10,
                "rule_priority_bypass_lan": 11,
                "rule_priority_gateway": 12,
                "rule_priority_catch_all": 13,
                "table_id": 10808
            },
            "owner_uid": os.geteuid(),
            "controller_pid": os.getpid(),
            "controller_starttime": 123
        })
        mock_popen.assert_called_once()
        assert mock_run.call_count == 2
        mock_run.assert_called_with(["ip", "link", "show", "tun0"], capture_output=True)
        controller._call_helper.assert_any_call("activate", {})

def test_tun_controller_rollback_failure():
    controller = TunController()
    controller.check_handshake = MagicMock(return_value=True)
    controller._call_helper = MagicMock(side_effect=[None, TunControllerError("rollback failed")])
    controller._generate_hev_config = MagicMock()
    
    plan = tun_plan.TunPlan(10808, "tun0", "10.0.0.2", "eth0", "1.1.1.1", "1.1.1.2", [], 10, 11, 12, 13)

    with patch("subprocess.Popen"), patch("subprocess.run"), patch("time.sleep"):
        with pytest.raises(TunRollbackError, match="Rollback failed during start"):
            controller.start(plan)
            
        # Should call rollback upon failure
        controller._call_helper.assert_any_call("rollback", {})

def test_main_argv_handling():
    # Test safe addition of -I physical_ip in main.py
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    src_dir = Path(__file__).parent.parent / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    from main import MainWindow
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if not app:
        app = QApplication([])

    with patch("tun_controller.TunController.check_availability", return_value=(True, "")), \
         patch("main.os.path.exists", return_value=True), \
         patch("tun_plan.create_plan") as mock_plan, \
         patch("process_manager.ProcessManager.start") as mock_start, \
         patch("tun_controller.TunController.start") as mock_tun_start, \
         patch("tun_controller.TunController.stop"), \
         patch("PySide6.QtWidgets.QMessageBox.critical") as mock_crit, \
         patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:

        window = MainWindow()
        window.mode_combo.setCurrentIndex(window.mode_combo.findData("tun"))
        
        plan = tun_plan.TunPlan(10808, "tun0", "10.0.0.2", "eth0", "192.168.1.10", "192.168.1.1", [], 10, 11, 12, 13)
        mock_plan.return_value = plan
        mock_start.return_value = True

        # Test normal injection
        window.args_input.setText("--fake -1")
        window.start_process()
        mock_start.assert_called_with("--fake -1 -I 192.168.1.10")
        mock_tun_start.assert_called_with(plan)
        
        window.stop_process()
        mock_start.reset_mock()
        mock_tun_start.reset_mock()

        # Test deduplication
        window.args_input.setText("--fake -1 -I 192.168.1.10")
        window.start_process()
        mock_start.assert_called_with("--fake -1 -I 192.168.1.10")
        mock_tun_start.assert_called_with(plan)

        window.stop_process()
        mock_start.reset_mock()
        mock_tun_start.reset_mock()

        # Test conflict
        window.args_input.setText("--fake -1 -I 10.0.0.5")
        window.start_process()
        mock_crit.assert_called_once()
        assert "Custom -I/--conn-ip is not supported" in mock_crit.call_args[0][2]
        mock_start.assert_not_called()

def test_tun_controller_pkexec_metadata(tmp_path):
    controller = TunController()
    fake_pkexec = tmp_path / "pkexec"
    fake_pkexec.touch()
    controller.pkexec_path = str(fake_pkexec)
    
    fake_helper = tmp_path / "helper"
    fake_helper.touch()
    controller.helper_path = str(fake_helper)
    
    fake_hev = tmp_path / "hev"
    fake_hev.touch()
    
    with patch("os.stat") as mock_stat, patch("os.access") as mock_access, patch("os.getuid", return_value=1000):
        class MockStatResult:
            def __init__(self, mode, uid):
                self.st_mode = mode
                self.st_uid = uid
        def fake_stat(path):
            import stat
            path_str = str(path)
            if path_str == str(fake_pkexec):
                return MockStatResult(stat.S_IFREG | 0o755, 0)
            elif path_str == str(fake_helper):
                return MockStatResult(stat.S_IFREG | 0o700, 0)
            elif path_str == str(fake_hev):
                return MockStatResult(stat.S_IFREG | 0o755, 1000)
            raise OSError()
            
        mock_stat.side_effect = fake_stat
        mock_access.return_value = True
        
        with patch.object(controller, "_get_hev_path", return_value=fake_hev):
            avail, reason = controller.check_availability()
            assert avail is True, reason
            
            def fake_stat_writable(path):
                import stat
                if path == str(fake_pkexec):
                    return MockStatResult(stat.S_IFREG | 0o777, 0)
                return fake_stat(path)
            mock_stat.side_effect = fake_stat_writable
            avail, reason = controller.check_availability()
            assert avail is False
            assert "pkexec unsafe" in reason
            
            def fake_stat_nonroot(path):
                import stat
                if path == str(fake_pkexec):
                    return MockStatResult(stat.S_IFREG | 0o755, 1000)
                return fake_stat(path)
            mock_stat.side_effect = fake_stat_nonroot
            avail, reason = controller.check_availability()
            assert avail is False
            assert "pkexec unsafe" in reason
