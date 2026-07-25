import os
import sys
import time
import socket

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from process_manager import ProcessManager

def test_process_manager_start_stop_success():
    pm = ProcessManager(sys.executable)
    outputs = []
    pm.on_output = lambda t: outputs.append(t)
    
    # Mock script that opens port 1081
    script = """
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('127.0.0.1', 1081))
s.listen(1)
print('mock started')
time.sleep(5)
"""
    # use port 1081 to avoid conflict if something uses 1080
    started = pm.start(["-c", script, "--port", "1081"])
    assert started == True
    assert pm.is_running() == True
    pm.stop(timeout=1.0)
    assert pm.is_running() == False

def test_process_manager_timeout():
    pm = ProcessManager(sys.executable)
    # Mock script that does NOT open port
    script = "import time; print('mock no port'); time.sleep(5)"
    # Should fail because port 1082 never opens
    started = pm.start(["-c", script, "--port", "1082"])
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
