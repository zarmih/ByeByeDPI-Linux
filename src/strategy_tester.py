import json
import os
import subprocess
import time
import socket
from PySide6.QtCore import QThread, Signal

class StrategyTesterThread(QThread):
    progress = Signal(int, int) # current, total
    result = Signal(str, str, float, str) # strategy_id, status, duration, http_code
    finished = Signal()

    def __init__(self, strategies, test_url, proxy_port=1081):
        super().__init__()
        self.strategies = strategies
        self.test_url = test_url
        self.proxy_port = proxy_port
        self._is_cancelled = False
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.ciadpi_path = os.path.join(self.base_dir, "vendor", "byedpi", "ciadpi")

    def cancel(self):
        self._is_cancelled = True

    def get_free_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]

    def test_strategy(self, strategy):
        # We replace {sni} with the domain of the test_url
        import urllib.parse
        parsed_url = urllib.parse.urlparse(self.test_url)
        domain = parsed_url.hostname or "www.google.com"

        args = strategy["args"].replace("{sni}", f'"{domain}"')
        port = self.get_free_port()

        import shlex
        cmd = [self.ciadpi_path, "--ip", "127.0.0.1", "--port", str(port)] + shlex.split(args)

        proc = None
        start_time = time.time()
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # Wait for proxy to bind
            time.sleep(0.5)

            # Test using curl with SOCKS5
            curl_cmd = [
                "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                "--socks5-hostname", f"127.0.0.1:{port}",
                "--max-time", "5",
                self.test_url
            ]
            curl_proc = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=10)
            duration = time.time() - start_time
            http_code = curl_proc.stdout.strip()
            
            if curl_proc.returncode == 0 and http_code.startswith("200"):
                return "Success", duration, http_code
            elif curl_proc.returncode == 0:
                return "Error", duration, http_code
            else:
                return "Fail", duration, http_code

        except subprocess.TimeoutExpired:
            return "Timeout", time.time() - start_time, ""
        except Exception as e:
            return "Error", time.time() - start_time, str(e)
        finally:
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def run(self):
        total = len(self.strategies)
        for i, strategy in enumerate(self.strategies):
            if self._is_cancelled:
                break
            
            self.progress.emit(i, total)
            status, duration, http_code = self.test_strategy(strategy)
            self.result.emit(strategy["id"], status, duration, http_code)
            
        self.progress.emit(total, total)
        self.finished.emit()
