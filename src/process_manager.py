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
        self._state_lock = threading.RLock()
        self._stop_notified = False
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
        self._stop_notified = False
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                shell=False
            )
            with self._state_lock:
                self.process = proc
        except Exception as e:
            self._emit_output(f"Failed to start process: {e}")
            return False

        reader = threading.Thread(target=self._read_output, args=(proc,), daemon=True)
        with self._state_lock:
            self._reader_thread = reader
        reader.start()

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

    def _notify_stop_once(self):
        callback = None
        with self._state_lock:
            if not self._stop_notified:
                self._stop_notified = True
                callback = self.on_stop
        if callback:
            callback()

    def stop(self, timeout: float = 3.0):
        with self._state_lock:
            proc = self.process
            reader = self._reader_thread

        if proc is None and reader is None:
            return

        self._emit_output("Stopping process...")
        self._stop_event.set()

        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        self._emit_output("Process did not stop gracefully, killing it...")
                        proc.kill()
                        proc.wait()
            except Exception as e:
                self._emit_output(f"Error while stopping process: {e}")
            finally:
                stdout = proc.stdout
                if stdout is not None and not stdout.closed:
                    stdout.close()

        current = threading.current_thread()
        if reader is not None and reader is not current and reader.is_alive():
            reader.join(timeout=max(timeout, 0.1) + 1.0)

        with self._state_lock:
            if self.process is proc:
                self.process = None
            if self._reader_thread is reader and (reader is None or not reader.is_alive()):
                self._reader_thread = None

        self._notify_stop_once()
        self._emit_output("Process stopped.")

    def is_running(self) -> bool:
        with self._state_lock:
            proc = self.process
        return proc is not None and proc.poll() is None

    def _read_output(self, proc: subprocess.Popen):
        unexpected = False
        try:
            stdout = proc.stdout
            if stdout is None:
                return
            for line in iter(stdout.readline, ''):
                if line:
                    self._emit_output(line.rstrip('\n'))
                if self._stop_event.is_set():
                    break
            proc.poll()
            unexpected = not self._stop_event.is_set()
        finally:
            stdout = proc.stdout
            if stdout is not None and not stdout.closed:
                stdout.close()
            current = threading.current_thread()
            with self._state_lock:
                if self.process is proc:
                    self.process = None
                if self._reader_thread is current:
                    self._reader_thread = None
            if unexpected:
                self._emit_output("Process exited unexpectedly.")
                self._notify_stop_once()

    def _emit_output(self, text: str):
        if self.on_output:
            self.on_output(text)

    def __del__(self):
        try:
            if self.process is not None or self._reader_thread is not None:
                self.stop(timeout=1.0)
        except Exception:
            pass
