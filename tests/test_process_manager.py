import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from process_manager import ProcessManager

def test_process_manager_start_stop():
    # Use python itself as a mock process
    pm = ProcessManager(sys.executable)
    
    outputs = []
    def on_output(text):
        outputs.append(text)
        
    pm.on_output = on_output
    
    # Run a simple python command that prints and sleeps
    script = "import sys, time; print('mock started'); sys.stdout.flush(); time.sleep(5)"
    started = pm.start(["-c", script])
    assert started == True
    
    time.sleep(1.0)
    assert pm.is_running() == True
    
    # Check if we got output
    assert any("mock started" in out for out in outputs)
    
    pm.stop(timeout=1.0)
    assert pm.is_running() == False

def test_process_manager_invalid_binary():
    pm = ProcessManager("/non/existent/binary")
    started = pm.start([])
    assert started == False
    assert pm.is_running() == False
