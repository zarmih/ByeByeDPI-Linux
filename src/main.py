import sys
import os
import shlex
import socket
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QLineEdit, QTextEdit, QMessageBox,
    QSystemTrayIcon, QMenu, QStyle
)
from PySide6.QtCore import Qt, Signal, Slot, QSettings
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QCheckBox

from process_manager import ProcessManager
from diagnostics import DiagnosticsDialog
from gnome_proxy import GnomeProxyAdapter

PROFILES = {
    "Profile 1 (Default)": "--disorder 1 --auto=torst --tlsrec 1+s",
    "Profile 2 (Fake)": "--fake -1 --tlsrec 1+s",
    "Profile 3 (Split)": "--split 1 --auto=torst --tlsrec 1+s",
    "Custom": ""
}

class MainWindow(QMainWindow):
    append_log_signal = Signal(str)
    process_stopped_signal = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ByeByeDPI Linux")
        self.resize(600, 400)

        self.settings = QSettings("ByeByeDPI", "ByeByeDPI-Linux")

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.binary_path = os.path.join(base_dir, "vendor", "byedpi", "ciadpi")

        self.pm = ProcessManager(self.binary_path)
        self.pm.on_output = self._on_process_output
        self.pm.on_stop = self._on_process_stop

        self.gnome_proxy = GnomeProxyAdapter()

        self.append_log_signal.connect(self.append_log)
        self.process_stopped_signal.connect(self.on_process_stopped)

        self.init_ui()
        self.init_tray()

        self.load_settings()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        top_layout = QHBoxLayout()

        self.profile_combo = QComboBox()
        self.profile_combo.addItems(list(PROFILES.keys()))
        self.profile_combo.currentTextChanged.connect(self.on_profile_changed)
        top_layout.addWidget(QLabel("Profile:"))
        top_layout.addWidget(self.profile_combo)

        self.args_input = QLineEdit()
        self.args_input.setReadOnly(True)
        top_layout.addWidget(QLabel("Args:"))
        top_layout.addWidget(self.args_input)

        self.library_btn = QPushButton("Library...")
        self.library_btn.clicked.connect(self.open_library)
        top_layout.addWidget(self.library_btn)

        layout.addLayout(top_layout)

        proxy_layout = QHBoxLayout()
        self.proxy_checkbox = QCheckBox("Set system proxy via GNOME (gsettings)")
        self.proxy_checkbox.setEnabled(self.gnome_proxy.is_available())
        if not self.gnome_proxy.is_available():
            self.proxy_checkbox.setToolTip("GNOME gsettings not available")
        proxy_layout.addWidget(self.proxy_checkbox)
        proxy_layout.addStretch()
        layout.addLayout(proxy_layout)

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

        self.check_proxy_btn = QPushButton("Check Proxy")
        self.check_proxy_btn.clicked.connect(self.check_proxy)
        controls_layout.addWidget(self.check_proxy_btn)

        self.diag_btn = QPushButton("Diagnostics")
        self.diag_btn.clicked.connect(self.run_diagnostics)
        controls_layout.addWidget(self.diag_btn)

        controls_layout.addStretch()

        layout.addLayout(controls_layout)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)

    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        # Use a standard icon for now
        icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
        self.tray_icon.setIcon(icon)

        self.tray_menu = QMenu()

        self.action_start = QAction("Start", self)
        self.action_start.triggered.connect(self.start_process)
        self.tray_menu.addAction(self.action_start)

        self.action_stop = QAction("Stop", self)
        self.action_stop.triggered.connect(self.stop_process)
        self.action_stop.setEnabled(False)
        self.tray_menu.addAction(self.action_stop)

        self.action_check = QAction("Check Proxy", self)
        self.action_check.triggered.connect(self.check_proxy)
        self.tray_menu.addAction(self.action_check)

        self.tray_menu.addSeparator()

        self.action_open = QAction("Open", self)
        self.action_open.triggered.connect(self.show)
        self.tray_menu.addAction(self.action_open)

        self.action_quit = QAction("Quit", self)
        self.action_quit.triggered.connect(self.quit_app)
        self.tray_menu.addAction(self.action_quit)

        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self.tray_activated)
        self.tray_icon.show()

    def load_settings(self):
        geom = self.settings.value("geometry")
        if geom:
            self.restoreGeometry(geom)

        profile = self.settings.value("profile", "Profile 1 (Default)")
        args = self.settings.value("custom_args", PROFILES["Profile 1 (Default)"])

        idx = self.profile_combo.findText(profile)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)
        else:
            self.profile_combo.setCurrentText("Custom")

        if self.profile_combo.currentText() == "Custom":
            self.args_input.setReadOnly(False)
            self.args_input.setText(args)
        else:
            self.args_input.setText(PROFILES.get(profile, ""))

        proxy_enabled = self.settings.value("gnome_proxy", False, type=bool)
        if self.gnome_proxy.is_available():
            self.proxy_checkbox.setChecked(proxy_enabled)

        # First-run diagnostics
        if not self.settings.value("first_run_done", False, type=bool):
            self.run_diagnostics()
            self.settings.setValue("first_run_done", True)

    def save_settings(self):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("profile", self.profile_combo.currentText())
        if self.profile_combo.currentText() == "Custom":
            self.settings.setValue("custom_args", self.args_input.text())
        else:
            self.settings.setValue("custom_args", PROFILES.get(self.profile_combo.currentText(), ""))

        self.settings.setValue("gnome_proxy", self.proxy_checkbox.isChecked())

    def on_profile_changed(self, profile_name):
        args = PROFILES.get(profile_name, "")
        if profile_name == "Custom":
            self.args_input.setReadOnly(False)
            # Retain whatever was previously set in Custom or clear if we want
        else:
            self.args_input.setReadOnly(True)
            self.args_input.setText(args)

    def open_library(self):
        from strategies_dialog import StrategiesDialog
        dialog = StrategiesDialog(self)
        dialog.strategy_selected.connect(self.on_strategy_selected)
        dialog.exec()

    def on_strategy_selected(self, args):
        self.profile_combo.setCurrentText("Custom")
        self.args_input.setText(args)

    def start_process(self):
        if not os.path.exists(self.binary_path):
            QMessageBox.critical(self, "Error", f"Binary not found: {self.binary_path}\nPlease build it first.")
            return

        args = self.args_input.text().strip()

        if self.pm.start(args):
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.action_start.setEnabled(False)
            self.action_stop.setEnabled(True)
            self.status_label.setText("Status: Running")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            self.profile_combo.setEnabled(False)
            self.args_input.setEnabled(False)
            self.proxy_checkbox.setEnabled(False)

            if self.proxy_checkbox.isChecked() and self.gnome_proxy.is_available():
                port = 1080
                try:
                    args_list = shlex.split(args)
                    for i, arg in enumerate(args_list):
                        if arg in ('-p', '--port') and i + 1 < len(args_list):
                            port = int(args_list[i+1])
                except:
                    pass
                self.gnome_proxy.apply_proxy(port)

        else:
            QMessageBox.warning(self, "Error", "Failed to start process or open port.")

    def stop_process(self):
        self.stop_btn.setEnabled(False)
        self.action_stop.setEnabled(False)
        self.pm.stop()
        if self.proxy_checkbox.isChecked() and self.gnome_proxy.is_available():
            self.gnome_proxy.restore_proxy()

    def check_proxy(self):
        args = self.args_input.text().strip()
        try:
            args_list = shlex.split(args)
        except:
            args_list = []

        port = 1080
        for i, arg in enumerate(args_list):
            if arg in ('-p', '--port') and i + 1 < len(args_list):
                try:
                    port = int(args_list[i+1])
                except ValueError:
                    pass

        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                QMessageBox.information(self, "Proxy Check", f"Proxy is reachable at 127.0.0.1:{port}")
        except OSError:
            QMessageBox.warning(self, "Proxy Check", f"Proxy is NOT reachable at 127.0.0.1:{port}")

    def run_diagnostics(self):
        diag = DiagnosticsDialog(self)
        diag.run_diagnostics(self.binary_path)
        diag.exec()

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
        self.action_start.setEnabled(True)
        self.action_stop.setEnabled(False)
        self.status_label.setText("Status: Stopped")
        self.status_label.setStyleSheet("color: gray; font-weight: bold;")
        self.profile_combo.setEnabled(True)
        if self.gnome_proxy.is_available():
            self.proxy_checkbox.setEnabled(True)
        if self.profile_combo.currentText() == "Custom":
            self.args_input.setEnabled(True)

    def closeEvent(self, event):
        self.save_settings()
        # Hide instead of quit if we have a tray icon
        if self.tray_icon.isVisible():
            event.ignore()
            self.hide()
        else:
            if self.proxy_checkbox.isChecked() and self.gnome_proxy.is_available():
                self.gnome_proxy.restore_proxy()
            self.pm.stop()
            event.accept()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show()

    def quit_app(self):
        self.save_settings()
        if self.proxy_checkbox.isChecked() and self.gnome_proxy.is_available():
            self.gnome_proxy.restore_proxy()
        self.pm.stop()
        QApplication.quit()

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Don't quit when the last window is closed, keep running in the tray
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
