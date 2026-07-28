import sys
import os
import time

# Set platform before importing anything GUI related
os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from PySide6.QtWidgets import QApplication
from main import MainWindow

def run_smoke_test():
    import faulthandler
    faulthandler.enable()
    import os
    os.environ["PYTEST_CURRENT_TEST"] = "smoke"
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.information = lambda *args, **kwargs: print(f"MOCK info: {args}")
    QMessageBox.warning = lambda *args, **kwargs: print(f"MOCK warning: {args}")
    QMessageBox.critical = lambda *args, **kwargs: print(f"MOCK critical: {args}")

    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    window = MainWindow()
    
    # Check initial state
    assert window.pm.is_running() == False
    
    print("Starting process...")
    window.start_process()
    
    # Wait for status to change to Running
    started = False
    for _ in range(50):
        if window.pm.is_running() and "Running" in window.status_label.text():
            started = True
            break
        app.processEvents()
        time.sleep(0.1)
    
    assert started, f"Process didn't start or label didn't update. Status: {window.status_label.text()}"
    
    # Check proxy via the button (simulated)
    print("Checking proxy...")
    window.check_proxy()
    
    print("Stopping process...")
    window.stop_process()
    
    stopped = False
    for _ in range(50):
        if not window.pm.is_running() and "Stopped" in window.status_label.text():
            stopped = True
            break
        app.processEvents()
        time.sleep(0.1)
        
    assert stopped, "Process didn't stop or label didn't update to Stopped"
    
    print("GUI smoke test passed.")
    window.close()
    app.processEvents()

if __name__ == "__main__":
    run_smoke_test()
