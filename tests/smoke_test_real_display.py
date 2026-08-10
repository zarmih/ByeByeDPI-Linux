import sys
import os
import time

# Keep an explicitly selected real backend (for example ``wayland``), but
# never inherit the dependency-free/offscreen test backend here.
if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
    del os.environ["QT_QPA_PLATFORM"]

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from main import MainWindow

def run_real_display_test():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    
    print("Real display window opened. Closing in 2 seconds...")
    QTimer.singleShot(2000, app.quit)
    
    sys.exit(app.exec())

if __name__ == "__main__":
    run_real_display_test()
