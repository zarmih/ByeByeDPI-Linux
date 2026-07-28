import os
import sys
import time
import socket

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from process_manager import ProcessManager

def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def test_process_manager_start_stop_success():
    pm = ProcessManager(sys.executable)
    outputs = []
    pm.on_output = lambda t: outputs.append(t)

    port = get_free_port()

    # Mock script that opens the port
    script = f"""
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('127.0.0.1', {port}))
s.listen(1)
print('mock started')
time.sleep(5)
"""
    started = pm.start(["-c", script, "--port", str(port)])
    assert started == True
    assert pm.is_running() == True
    pm.stop(timeout=1.0)
    assert pm.is_running() == False

def test_process_manager_timeout():
    pm = ProcessManager(sys.executable)
    port = get_free_port()
    # Mock script that does NOT open port
    script = "import time; print('mock no port'); time.sleep(5)"
    # Should fail because port never opens
    started = pm.start(["-c", script, "--port", str(port)])
    assert started == False
    assert pm.is_running() == False

def test_process_manager_invalid_port():
    pm = ProcessManager(sys.executable)
    started = pm.start(["-c", "pass", "--port", "99999"])
    assert started == False

def test_process_manager_invalid_ip():
    pm = ProcessManager(sys.executable)
    started = pm.start(["-c", "pass", "--ip", "0.0.0.0"])
    assert started == False

def test_process_manager_stop_idempotent_and_closes_stdout():
    pm = ProcessManager(sys.executable)
    port = get_free_port()
    script = f"import socket, time\ns=socket.socket()\ns.bind(('127.0.0.1', {port}))\ns.listen(1)\nprint('mock started')\ntime.sleep(5)"

    pm.start(["-c", script, "--port", str(port)])
    assert pm.is_running()

    proc = pm.process
    thread = pm._reader_thread

    pm.stop(timeout=1.0)
    assert not pm.is_running()
    assert pm.process is None

    assert proc.stdout.closed, "stdout pipe should be closed after stop()"
    assert not thread.is_alive(), "Reader thread should be joined and stopped"

    # Repeated stop should not fail
    pm.stop()

def test_process_manager_unexpected_exit():
    pm = ProcessManager(sys.executable)
    port = get_free_port()
    # Script opens port and then immediately exits
    script = f"import socket, time\ns=socket.socket()\ns.bind(('127.0.0.1', {port}))\ns.listen(1)\n"

    stop_called = 0
    def on_stop():
        nonlocal stop_called
        stop_called += 1

    pm.on_stop = on_stop

    pm.start(["-c", script, "--port", str(port)])

    # Wait for it to unexpectedly exit and thread to finish
    time.sleep(1.5)

    assert stop_called == 1, "on_stop should be called exactly once on unexpected exit"
    assert pm.process is None, "process should be cleaned up on unexpected exit"
