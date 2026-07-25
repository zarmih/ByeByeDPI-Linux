import subprocess
import threading
import time
import os
import signal
import shlex
import socket
from typing import List, Callable, Optional, Union

class ProcessManager:
    def __init__(self, binary_path: str):
        self.binary_path = binary_path
        self.process: Optional[subprocess.Popen] = None
        self._stop_event = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None
        self.on_output: Optional[Callable[[str], None]] = None
        self.on_stop: Optional[Callable[[], None]] = None

    def start(self, args: Union[str, List[str]]) -> bool:
        if self.is_running():
            return False

        if not os.path.isfile(self.binary_path) or not os.access(self.binary_path, os.X_OK):
            self._emit_output(f"Error: Binary not found or not executable: {self.binary_path}")
            return False

        # Parse args
        if isinstance(args, str):
            if any(ord(c) < 32 and c not in '\t\n\r' for c in args):
                self._emit_output("Error: Control characters are not allowed in arguments.")
                return False
            try:
                args_list = shlex.split(args)
            except ValueError as e:
                self._emit_output(f"Error parsing arguments: {e}")
                return False
        else:
            args_list = args

        # Analyze arguments for port and IP
        port = 1080
        ip = "127.0.0.1"
        i = 0
        while i < len(args_list):
            arg = args_list[i]
            if arg in ('-p', '--port'):
                if i + 1 < len(args_list):
                    try:
                        port = int(args_list[i+1])
                    except ValueError:
                        self._emit_output("Error: Invalid port specified.")
                        return False
                else:
                    self._emit_output("Error: Empty port specified.")
                    return False
            elif arg == '--ip':
                if i + 1 < len(args_list):
                    ip = args_list[i+1]
                else:
                    self._emit_output("Error: Empty IP specified.")
                    return False
            i += 1

        if port <= 0 or port > 65535:
            self._emit_output("Error: Port out of range.")
            return False

        if ip != "127.0.0.1":
            self._emit_output("Error: Binding is only allowed on 127.0.0.1 for security.")
            return False

        # Check if port is already in use
        if self._is_port_in_use(ip, port):
            self._emit_output(f"Error: Port {port} is already in use.")
            return False

        # Add explicit IP binding just to be safe
        if '--ip' not in args_list:
            args_list.extend(['--ip', '127.0.0.1'])

        cmd = [self.binary_path] + args_list
        self._emit_output(f"Starting process: {' '.join(cmd)}")

        self._stop_event.clear()
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                shell=False
            )
        except Exception as e:
            self._emit_output(f"Failed to start process: {e}")
            return False

        self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self._reader_thread.start()

        # Check readiness
        if not self._wait_for_port(ip, port, timeout=3.0):
            self._emit_output(f"Error: Process started but port {port} didn't open in time.")
            self.stop()
            return False

        return True

    def _is_port_in_use(self, ip: str, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex((ip, port)) == 0

    def _wait_for_port(self, ip: str, port: int, timeout: float) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            if not self.is_running():
                return False
            if self._is_port_in_use(ip, port):
                return True
            time.sleep(0.1)
        return False

    def stop(self, timeout: float = 3.0):
        if not self.is_running():
            return

        self._emit_output("Stopping process...")
        self._stop_event.set()
        
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._emit_output("Process did not stop gracefully, killing it...")
                self.process.kill()
                self.process.wait()
            except Exception as e:
                self._emit_output(f"Error while stopping process: {e}")

        self.process = None
        if self.on_stop:
            self.on_stop()
        self._emit_output("Process stopped.")

    def is_running(self) -> bool:
        if self.process is None:
            return False
        return self.process.poll() is None

    def _read_output(self):
        if not self.process or not self.process.stdout:
            return
            
        for line in iter(self.process.stdout.readline, ''):
            if line:
                self._emit_output(line.rstrip('\n'))
            if self._stop_event.is_set():
                break
                
        if self.process:
            self.process.poll()
            
        if not self._stop_event.is_set():
            self._emit_output("Process exited unexpectedly.")
            if self.on_stop:
                self.on_stop()
            self.process = None

    def _emit_output(self, text: str):
        if self.on_output:
            self.on_output(text)

    def __del__(self):
        if self.is_running():
            self.stop(timeout=1.0)
