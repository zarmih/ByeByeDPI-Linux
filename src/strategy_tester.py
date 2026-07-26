import json
import os
import subprocess
import time
import socket
import shlex
from typing import List, Dict, Any, Tuple
from PySide6.QtCore import QThread, Signal

import threading
import statistics

class StrategyTesterThread(QThread):
    # Emit progress: strategy_idx, total_strategies, target_idx, total_targets
    progress = Signal(object, object, object, object) 
    
    # Emit strategy start: strategy_id
    strategy_started = Signal(object)
    
    # Emit target result: strategy_id, target_id, status, duration, http_code, error_msg
    target_result = Signal(object, object, object, object, object, object)
    
    # Emit strategy aggregate: strategy_id, passed, total, avg_time, median_time, timeout, error
    strategy_finished = Signal(object, object, object, object, object, object, object)
    
    finished = Signal()

    def __init__(self, strategies: List[Dict[str, Any]], targets: List[Dict[str, Any]], proxy_port: int = 1081):
        super().__init__()
        self.strategies = strategies
        self.targets = targets
        self.proxy_port = proxy_port
        self._is_cancelled = False
        self._pause_event = threading.Event()
        self._pause_event.set()  # Initial state is not paused
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.ciadpi_path = os.path.join(self.base_dir, "vendor", "byedpi", "ciadpi")

    def cancel(self):
        self._is_cancelled = True
        self.resume() # Unblock if paused

    def pause(self):
        self._pause_event.clear()
        
    def resume(self):
        self._pause_event.set()

    def get_free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]

    def test_single_target(self, target: Dict[str, Any], port: int) -> Tuple[str, float, str, str]:
        url = target.get("url")
        start_time = time.time()
        
        # We use curl with SOCKS5, similar to Android's connection logic.
        # Android (SiteCheckUtils.kt) policy:
        # 1. Method: GET (openConnection), Follow redirects = true.
        # 2. Timeout: connect/read timeout applied.
        # 3. Headers: Connection: close. (No custom User-Agent).
        # 4. Success: Any HTTP status code is accepted as long as the TLS handshake 
        #    and stream read complete up to Content-Length (or 1MB).
        # We use -L (redirects), --connect-timeout 5, -H "Connection: close".
        # We rely on subprocess timeout=10 to bound total execution.
        # A curl exit code 0 means full transfer (matches Android actualLength >= declaredLength).
        curl_cmd = [
            "curl", "-s", "-L", "-o", "/dev/null", "-w", "%{http_code}",
            "--socks5-hostname", f"127.0.0.1:{port}",
            "--connect-timeout", "5",
            "-H", "Connection: close",
            url
        ]
        
        try:
            proc = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=10)
            duration = time.time() - start_time
            http_code = proc.stdout.strip()
            
            if proc.returncode == 0:
                # HTTPS interception is impossible without cert errors, so any successful 
                # TLS connection (even 404, 403, 302) means DPI did not drop/reset the connection.
                return "Success", duration, http_code, ""
            elif proc.returncode in (28, 7): # Timeout or could not connect
                return "Timeout", duration, http_code, proc.stderr.strip() or "Timeout"
            else:
                return "Error", duration, http_code, f"cURL error {proc.returncode}: {proc.stderr.strip()}"
                
        except subprocess.TimeoutExpired:
            return "Timeout", time.time() - start_time, "", "Process timeout"
        except Exception as e:
            return "Error", time.time() - start_time, "", str(e)

    def run(self):
        total_strategies = len(self.strategies)
        total_targets = len(self.targets)
        
        for s_idx, strategy in enumerate(self.strategies):
            self._pause_event.wait()
            if self._is_cancelled:
                break
                
            self.strategy_started.emit(strategy["id"])
            
            # {sni} replacement should ideally happen per target, but ciadpi accepts only one args set at start.
            # We pick the first target's host as the {sni} placeholder if needed.
            first_target_host = self.targets[0]["host"] if self.targets else "www.google.com"
            args = strategy["args"].replace("{sni}", f'"{first_target_host}"')
            
            port = self.get_free_port()
            cmd = [self.ciadpi_path, "--ip", "127.0.0.1", "--port", str(port)] + shlex.split(args)
            
            proc = None
            passed_count = 0
            timeout_count = 0
            error_count = 0
            success_durations = []
            
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(0.5) # Wait for proxy to bind
                
                for t_idx, target in enumerate(self.targets):
                    self._pause_event.wait()
                    if self._is_cancelled:
                        break
                        
                    self.progress.emit(s_idx, total_strategies, t_idx, total_targets)
                    
                    status, duration, http_code, error_msg = self.test_single_target(target, port)
                    
                    if status == "Success":
                        passed_count += 1
                        success_durations.append(duration)
                    elif status == "Timeout":
                        timeout_count += 1
                    else:
                        error_count += 1
                        
                    self.target_result.emit(strategy["id"], target["target_id"], status, duration, http_code, error_msg)
                    
            finally:
                if proc:
                    proc.terminate()
                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        
            if self._is_cancelled:
                break
                
            avg_time = statistics.mean(success_durations) if success_durations else 0.0
            median_time = statistics.median(success_durations) if success_durations else 0.0
            self.strategy_finished.emit(strategy["id"], passed_count, total_targets, avg_time, median_time, timeout_count, error_count)
            
        self.progress.emit(total_strategies, total_strategies, total_targets, total_targets)
        self.finished.emit()
