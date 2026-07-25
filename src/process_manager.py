import subprocess
import threading
import time
import os
import signal
import shlex
from typing import List, Callable, Optional

class ProcessManager:
    def __init__(self, binary_path: str):
        self.binary_path = binary_path
        self.process: Optional[subprocess.Popen] = None
        self._stop_event = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None
        self.on_output: Optional[Callable[[str], None]] = None
        self.on_stop: Optional[Callable[[], None]] = None

    def start(self, args: str | List[str]) -> bool:
        if self.is_running():
            return False

        if not os.path.isfile(self.binary_path) or not os.access(self.binary_path, os.X_OK):
            self._emit_output(f"Error: Binary not found or not executable: {self.binary_path}")
            return False

        if isinstance(args, str):
            try:
                # Use shlex to safely split arguments
                args_list = shlex.split(args)
            except ValueError as e:
                self._emit_output(f"Error parsing arguments: {e}")
                return False
        else:
            args_list = args

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
                shell=False # CRITICAL: No shell=True for security
            )
        except Exception as e:
            self._emit_output(f"Failed to start process: {e}")
            return False

        self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self._reader_thread.start()
        return True

    def stop(self, timeout: float = 3.0):
        if not self.is_running():
            return

        self._emit_output("Stopping process...")
        self._stop_event.set()
        
        # Graceful terminate
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
                
        # Wait for process to fully terminate if it hasn't
        if self.process:
            self.process.poll()
            
        if not self._stop_event.is_set():
            # Process died on its own
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
