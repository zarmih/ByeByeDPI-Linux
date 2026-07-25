import sys
import os
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QLineEdit, QTextEdit, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal, Slot

from process_manager import ProcessManager

PROFILES = {
    "Profile 1 (Default)": "--disorder 1 --auto=torst --tlsrec 1+s",
    "Profile 2 (Fake)": "--fake -1 --tlsrec 1+s",
    "Profile 3 (Split)": "--split 1 --auto=torst --tlsrec 1+s",
    "Custom": ""
}

class MainWindow(QMainWindow):
    # Signals for thread-safe UI updates
    append_log_signal = Signal(str)
    process_stopped_signal = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ByeByeDPI Linux")
        self.resize(600, 400)

        # Path to ciadpi binary
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.binary_path = os.path.join(base_dir, "vendor", "byedpi", "ciadpi")
        
        self.pm = ProcessManager(self.binary_path)
        self.pm.on_output = self._on_process_output
        self.pm.on_stop = self._on_process_stop

        self.append_log_signal.connect(self.append_log)
        self.process_stopped_signal.connect(self.on_process_stopped)

        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Top panel: profiles and custom args
        top_layout = QHBoxLayout()
        
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(list(PROFILES.keys()))
        self.profile_combo.currentTextChanged.connect(self.on_profile_changed)
        top_layout.addWidget(QLabel("Profile:"))
        top_layout.addWidget(self.profile_combo)

        self.args_input = QLineEdit()
        self.args_input.setText(PROFILES["Profile 1 (Default)"])
        self.args_input.setReadOnly(True)
        top_layout.addWidget(QLabel("Args:"))
        top_layout.addWidget(self.args_input)

        layout.addLayout(top_layout)

        # Controls panel
        controls_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.start_process)
        controls_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_process)
        self.stop_btn.setEnabled(False)
        controls_layout.addWidget(self.stop_btn)

        self.status_label = QLabel("Status: Stopped")
        self.status_label.setStyleSheet("color: gray; font-weight: bold;")
        controls_layout.addWidget(self.status_label)
        controls_layout.addStretch()

        layout.addLayout(controls_layout)

        # Log area
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)

    def on_profile_changed(self, profile_name):
        args = PROFILES.get(profile_name, "")
        if profile_name == "Custom":
            self.args_input.setReadOnly(False)
            self.args_input.setText("")
        else:
            self.args_input.setReadOnly(True)
            self.args_input.setText(args)

    def start_process(self):
        if not os.path.exists(self.binary_path):
            QMessageBox.critical(self, "Error", f"Binary not found: {self.binary_path}\nPlease build it first.")
            return

        args = self.args_input.text().strip()
        
        if self.pm.start(args):
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.status_label.setText("Status: Running (SOCKS5 usually at 127.0.0.1:1080)")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            self.profile_combo.setEnabled(False)
            self.args_input.setEnabled(False)

    def stop_process(self):
        self.stop_btn.setEnabled(False) # Disable to prevent multiple clicks
        self.pm.stop()

    def _on_process_output(self, text: str):
        self.append_log_signal.emit(text)

    def _on_process_stop(self):
        self.process_stopped_signal.emit()

    @Slot(str)
    def append_log(self, text: str):
        self.log_area.append(text)

    @Slot()
    def on_process_stopped(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Status: Stopped")
        self.status_label.setStyleSheet("color: gray; font-weight: bold;")
        self.profile_combo.setEnabled(True)
        if self.profile_combo.currentText() == "Custom":
            self.args_input.setEnabled(True)

    def closeEvent(self, event):
        self.pm.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
