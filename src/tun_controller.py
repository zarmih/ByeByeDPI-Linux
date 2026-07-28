import os
import time
import json
import subprocess
import tempfile
import atexit
import uuid
import stat
from pathlib import Path
from typing import Optional

import tun_plan

class TunControllerError(Exception):
    pass

class TunRollbackError(TunControllerError):
    pass

class TunController:
    def __init__(self):
        self.helper_path = "/usr/libexec/byebyedpi-linux/tun-helper"
        self.pkexec_path = "/usr/bin/pkexec"
        self.hev_process: Optional[subprocess.Popen] = None
        self.hev_config_path: Optional[str] = None
        self.tun_plan_obj: Optional[tun_plan.TunPlan] = None
        self.session_id = uuid.uuid4().hex + uuid.uuid4().hex
        self.recovery_required = False
        self._atexit_func = lambda: self._cleanup_atexit()
        atexit.register(self._atexit_func)

    def _cleanup_atexit(self):
        try:
            self.stop()
        except Exception:
            pass

    def _get_hev_path(self) -> Path:
        base_dir = Path(__file__).resolve().parent.parent
        return base_dir / "vendor" / "hev-socks5-tunnel" / "bin" / "hev-socks5-tunnel"

    def check_availability(self) -> tuple[bool, str]:
        hev_bin = self._get_hev_path()
        if not os.path.isfile(self.helper_path):
            return False, "Helper missing"
        if not hev_bin.exists():
            return False, "HEV missing"

        try:
            st_pkexec = os.stat(self.pkexec_path)
            if not stat.S_ISREG(st_pkexec.st_mode) or st_pkexec.st_uid != 0 or not os.access(self.pkexec_path, os.X_OK) or (st_pkexec.st_mode & 0o022):
                return False, "pkexec unsafe"

            st_helper = os.stat(self.helper_path)
            mode = st_helper.st_mode & 0o777
            if not stat.S_ISREG(st_helper.st_mode) or st_helper.st_uid != 0:
                return False, "Helper not root"
            if not (mode == 0o700 or (not (st_helper.st_mode & 0o022) and (st_helper.st_mode & stat.S_IXUSR))):
                return False, "Helper unsafe mode"

            st_hev = os.stat(hev_bin)
            if not stat.S_ISREG(st_hev.st_mode) or st_hev.st_uid != os.getuid() or not os.access(hev_bin, os.X_OK):
                return False, "HEV unsafe"
            if st_hev.st_mode & (stat.S_ISUID | stat.S_ISGID):
                return False, "HEV has SUID/SGID"
            if st_hev.st_mode & 0o022:
                return False, "HEV group/world-writable"

            return True, ""
        except OSError:
            return False, "Stat failed"

    def is_helper_installed(self) -> bool:
        return self.check_availability()[0]

    def _generate_hev_config(self) -> str:
        if not self.tun_plan_obj:
            raise TunControllerError("TUN Plan is missing")
            
        config = f"""
tunnel:
  name: {self.tun_plan_obj.tun_interface}
  mtu: 1500
  ipv4: {self.tun_plan_obj.tun_ip}
  ipv6: ''
  icmp: 'reply'

socks5:
  port: 10808
  address: 127.0.0.1
  udp: 'udp'
"""
        run_dir = "/run/user/" + str(os.getuid()) + "/byebyedpi-linux"
        try:
            os.makedirs(run_dir, mode=0o700, exist_ok=True)
            st = os.stat(run_dir)
            if st.st_uid != os.getuid() or (st.st_mode & 0o777) != 0o700:
                raise TunControllerError("Unsafe config directory permissions")
        except OSError:
            run_dir = tempfile.mkdtemp(prefix="byebyedpi_")
            os.chmod(run_dir, 0o700)
            
        fd, path = tempfile.mkstemp(prefix="hev_config_", suffix=".yml", dir=run_dir)
        with os.fdopen(fd, 'w') as f:
            os.chmod(path, 0o600)
            f.write(config)
        self.hev_config_path = path
        return path

    def _call_helper(self, action: str, data: dict) -> dict:
        if not self.is_helper_installed():
            raise TunControllerError("Helper, pkexec or backend not installed or unsafe")

        cmd = [self.pkexec_path, self.helper_path, action]
        
        data["session_id"] = self.session_id
        input_data = json.dumps(data)
        
        try:
            result = subprocess.run(
                cmd,
                input=input_data,
                text=True,
                capture_output=True,
                check=True
            )
            if action == "status":
                return json.loads(result.stdout)
            return {}
        except subprocess.CalledProcessError as e:
            raise TunControllerError(f"Helper failed ({action})") from e
        except json.JSONDecodeError:
            return {}

    def get_controller_starttime(self) -> int:
        pid = os.getpid()
        try:
            with open(f"/proc/{pid}/stat", "r") as f:
                parts = f.read().split()
                if len(parts) >= 22:
                    return int(parts[21])
        except OSError:
            pass
        return 0

    def check_handshake(self) -> bool:
        try:
            res = self._call_helper("status", {})
            if res and res.get("version") == 1:
                return True
        except TunControllerError:
            pass
        return False

    def start(self, plan: tun_plan.TunPlan) -> None:
        if self.hev_process:
            return

        if not self.check_handshake():
            raise TunControllerError("Helper handshake failed")

        try:
            self.tun_plan_obj = plan

            plan_dict = {
                "tun_interface": self.tun_plan_obj.tun_interface,
                "tun_ip": self.tun_plan_obj.tun_ip,
                "physical_ip": self.tun_plan_obj.physical_ip,
                "gateway_ip": self.tun_plan_obj.gateway_ip,
                "connected_prefixes": self.tun_plan_obj.connected_prefixes,
                "rule_priority_bypass_physical": self.tun_plan_obj.rule_priority_bypass_physical,
                "rule_priority_bypass_lan": self.tun_plan_obj.rule_priority_bypass_lan, "rule_priority_gateway": self.tun_plan_obj.rule_priority_gateway,
                "rule_priority_catch_all": self.tun_plan_obj.rule_priority_catch_all,
                "table_id": self.tun_plan_obj.table_id
            }

            self._call_helper("prepare", {
                "plan": plan_dict,
                "owner_uid": os.geteuid(),
                "controller_pid": os.getpid(),
                "controller_starttime": self.get_controller_starttime()
            })

            config_path = self._generate_hev_config()
            hev_bin = self._get_hev_path()

            self.hev_process = subprocess.Popen(
                [str(hev_bin), config_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            ready = False
            for _ in range(50):
                if self.hev_process.poll() is not None:
                    raise TunControllerError("hev-socks5-tunnel failed to start")
                
                # Use os.system or simple subprocess to check if iface exists without root
                if subprocess.run(["ip", "link", "show", self.tun_plan_obj.tun_interface], capture_output=True).returncode == 0:
                    ready = True
                    break
                time.sleep(0.1)
                
            if not ready:
                raise TunControllerError(f"hev-socks5-tunnel did not create interface {self.tun_plan_obj.tun_interface} in time")

            self._call_helper("activate", {})

        except Exception as e:
            rollback_failed = False
            try:
                self._call_helper("rollback", {})
            except TunControllerError:
                rollback_failed = True

            if rollback_failed:
                self.recovery_required = True
                raise TunRollbackError(f"Rollback failed during start. TUN state corrupted. Manual recovery required. Original error: {e}") from e

            if self.hev_process:
                self.hev_process.terminate()
                try:
                    self.hev_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.hev_process.kill()
                self.hev_process = None
            raise TunControllerError(f"Failed to start TUN mode: {e}") from e

    def stop(self) -> None:
        if self.recovery_required:
            return

        rollback_failed = False
        try:
            self._call_helper("rollback", {})
        except TunControllerError:
            rollback_failed = True

        if rollback_failed:
            self.recovery_required = True
            raise TunRollbackError("Rollback failed! TUN state corrupted. Manual recovery required.")

        if self.hev_process:
            self.hev_process.terminate()
            try:
                self.hev_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.hev_process.kill()
            self.hev_process = None

        if self.hev_config_path and os.path.exists(self.hev_config_path):
            os.remove(self.hev_config_path)
            self.hev_config_path = None

    def recover(self) -> None:
        if self.is_helper_installed():
            try:
                subprocess.run(
                    [self.pkexec_path, self.helper_path, "recover"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False
                )
            except OSError:
                pass
