import sys
import os
import shlex
import socket
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QLineEdit, QTextEdit, QMessageBox,
    QSystemTrayIcon, QMenu, QStyle
)
from PySide6.QtCore import Qt, Signal, Slot, QSettings, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QCheckBox

from process_manager import ProcessManager
from diagnostics import DiagnosticsDialog
from version import __version__
from gnome_proxy import GnomeProxyAdapter
import settings_schema
import autostart_manager
from PySide6.QtWidgets import QFileDialog

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
        self.setWindowTitle(f"ByeByeDPI Linux {__version__}")
        self.resize(600, 400)
        self._quitting = False
        self._tray_notice_shown = False

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
        self._recover_pending_proxy()

        first_run_report = self.settings.value("first_run_report", None)
        show_diag = False
        if not self._is_test_environment():
            if not first_run_report:
                show_diag = True
            elif isinstance(first_run_report, dict) and first_run_report.get("status") == "FAIL":
                show_diag = True

        if show_diag:
            QTimer.singleShot(0, self._show_first_run_diagnostics)
        elif not os.path.exists(self.binary_path):
            self.start_btn.setEnabled(False)
            self.start_btn.setToolTip("ciadpi is missing. Check diagnostics.")

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        top_layout = QHBoxLayout()

        self.fav_checkbox = QCheckBox("★")
        self.fav_checkbox.setToolTip("Mark strategy as Favorite")
        self.fav_checkbox.toggled.connect(self.on_fav_toggled)
        top_layout.addWidget(self.fav_checkbox)

        self.profile_combo = QComboBox()
        self.profile_combo.addItems(list(PROFILES.keys()))
        self.profile_combo.currentTextChanged.connect(self.on_profile_changed)
        top_layout.addWidget(QLabel("Profile:"))
        top_layout.addWidget(self.profile_combo)

        menu_bar = self.menuBar()
        settings_menu = menu_bar.addMenu("Settings")

        self.action_export = QAction("Export Settings...", self)
        self.action_export.triggered.connect(self.export_settings)
        settings_menu.addAction(self.action_export)

        self.action_import = QAction("Import Settings...", self)
        self.action_import.triggered.connect(self.import_settings)
        settings_menu.addAction(self.action_import)

        settings_menu.addSeparator()

        self.action_autostart = QAction("Start at login", self)
        self.action_autostart.setCheckable(True)
        self.action_autostart.toggled.connect(self.toggle_autostart)
        settings_menu.addAction(self.action_autostart)

        help_menu = menu_bar.addMenu("Help")
        self.action_update = QAction("Check for App Updates...", self)
        self.action_update.triggered.connect(self.check_app_updates)
        help_menu.addAction(self.action_update)

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

        self.reset_btn = QPushButton("Reset Settings")
        self.reset_btn.clicked.connect(self.reset_settings)
        controls_layout.addWidget(self.reset_btn)

        controls_layout.addStretch()

        layout.addLayout(controls_layout)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)

    def init_tray(self):
        self.tray_available = QSystemTrayIcon.isSystemTrayAvailable()
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
        if self.tray_available:
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

        self.action_autostart.setChecked(autostart_manager.is_autostart_enabled())
        self._update_fav_checkbox()

    def save_settings(self):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("profile", self.profile_combo.currentText())
        if self.profile_combo.currentText() == "Custom":
            custom_args = self.args_input.text()
            if self._args_are_safe_to_store(custom_args):
                self.settings.setValue("custom_args", custom_args)
            else:
                self.settings.remove("custom_args")
        else:
            self.settings.setValue("custom_args", PROFILES.get(self.profile_combo.currentText(), ""))

        self.settings.setValue("gnome_proxy", self.proxy_checkbox.isChecked())
        self.settings.sync()

    @staticmethod
    def _args_are_safe_to_store(args: str) -> bool:
        lowered = args.casefold()
        sensitive = (
            "password=", "secret=", "token=", "api_key=", "apikey=",
            "cookie=", "authorization=",
        )
        return not any(marker in lowered for marker in sensitive)

    @staticmethod
    def _is_test_environment() -> bool:
        return bool(
            os.environ.get("PYTEST_CURRENT_TEST")
            or os.environ.get("QT_QPA_PLATFORM") == "offscreen"
        )

    def reset_settings(self):
        self.settings.clear()
        self.settings.sync()
        QMessageBox.information(
            self,
            "Settings Reset",
            "Saved settings were cleared. Defaults will be used on the next launch.",
        )

    def _show_first_run_diagnostics(self):
        diag = DiagnosticsDialog(self.binary_path, self)
        diag.run_diagnostics()
        diag.exec()
        if diag.last_report:
            report_summary = {
                "schema_version": diag.last_report.get("schema_version", 1),
                "timestamp": diag.last_report.get("timestamp", 0),
                "status": diag.last_report.get("status", "FAIL")
            }
            self.settings.setValue("first_run_report", report_summary)
            self.settings.sync()

            if not os.path.exists(self.binary_path):
                self.start_btn.setEnabled(False)
                self.start_btn.setToolTip("ciadpi is missing. Check diagnostics.")
            else:
                self.start_btn.setEnabled(True)
                self.start_btn.setToolTip("")

    def _recover_pending_proxy(self):
        if not self.gnome_proxy.has_journal():
            return
        if not self.gnome_proxy.recover_if_needed():
            message = (
                "A previous GNOME proxy session could not be restored. "
                "The recovery journal was retained.\n\n"
                + self.gnome_proxy.last_error
            )
            QTimer.singleShot(
                0,
                lambda: QMessageBox.critical(self, "Proxy Recovery Failed", message),
            )

    def _update_fav_checkbox(self):
        profile = self.profile_combo.currentText()
        if profile == "Custom":
            self.fav_checkbox.setVisible(False)
            return
        self.fav_checkbox.setVisible(True)
        favs = self.settings.value("favorites_strategies", [])
        if favs is None: favs = []
        elif isinstance(favs, str): favs = [favs]
        elif not isinstance(favs, (list, tuple)): favs = []
        else: favs = list(favs)

        # Block signals to avoid toggling trigger
        self.fav_checkbox.blockSignals(True)
        self.fav_checkbox.setChecked(profile in favs)
        self.fav_checkbox.blockSignals(False)

    def on_fav_toggled(self, checked):
        profile = self.profile_combo.currentText()
        if profile == "Custom": return
        favs = self.settings.value("favorites_strategies", [])
        if favs is None: favs = []
        elif isinstance(favs, str): favs = [favs]
        elif not isinstance(favs, (list, tuple)): favs = []
        else: favs = list(favs)

        if checked and profile not in favs:
            favs.append(profile)
        elif not checked and profile in favs:
            favs.remove(profile)

        self.settings.setValue("favorites_strategies", favs)
        self.settings.sync()

    def export_settings(self):
        # Gather all settings into a dict
        d = {}
        for k in self.settings.allKeys():
            d[k] = self.settings.value(k)
        d["autostart"] = autostart_manager.is_autostart_enabled()

        json_str = settings_schema.export_settings(d)
        path, _ = QFileDialog.getSaveFileName(self, "Export Settings", "byebyedpi-settings.json", "JSON Files (*.json)")
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(json_str)
                QMessageBox.information(self, "Success", "Settings exported successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export settings: {e}")

    def import_settings(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Settings", "", "JSON Files (*.json)")
        if not path:
            return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                json_str = f.read()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to read file: {e}")
            return

        try:
            updates = settings_schema.import_settings(json_str)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Invalid settings file: {e}")
            return

        # Preview dialog
        added_changed = []
        for k, v in updates.items():
            added_changed.append(f"{k}: {v}")

        preview = "The following settings will be applied:\n" + "\n".join(added_changed)
        reply = QMessageBox.question(self, "Import Settings Preview", preview + "\n\nProceed?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.No:
            return

        # Apply updates
        for k, v in updates.items():
            if k == "autostart":
                autostart_manager.set_autostart(v)
            else:
                self.settings.setValue(k, v)
        self.settings.sync()
        self.load_settings()
        QMessageBox.information(self, "Success", "Settings imported successfully.")

    def toggle_autostart(self, checked):
        if self._is_test_environment():
            QMessageBox.warning(self, "Test Environment", "Autostart changes are disabled in tests.")
            self.action_autostart.setChecked(not checked)
            return

        success, msg = autostart_manager.set_autostart(checked)
        if not success:
            QMessageBox.warning(self, "Autostart Error", msg)
            self.action_autostart.setChecked(not checked)

    def _proxy_port(self) -> int:
        try:
            args_list = shlex.split(self.args_input.text().strip())
        except ValueError:
            return 1080
        for index, arg in enumerate(args_list[:-1]):
            if arg in ("-p", "--port"):
                try:
                    port = int(args_list[index + 1])
                except ValueError:
                    return 1080
                return port if 1 <= port <= 65535 else 1080
        return 1080

    def on_profile_changed(self, profile_name):
        args = PROFILES.get(profile_name, "")
        if profile_name == "Custom":
            self.args_input.setReadOnly(False)
            # Retain whatever was previously set in Custom or clear if we want
        else:
            self.args_input.setReadOnly(True)
            self.args_input.setText(args)
        self._update_fav_checkbox()

    def open_library(self):
        from strategies_dialog import StrategiesDialog
        dialog = StrategiesDialog(self)
        dialog.strategy_selected.connect(self.on_strategy_selected)
        dialog.exec()

    def check_app_updates(self):
        from app_update_dialog import AppUpdateDialog
        dialog = AppUpdateDialog(self)
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
                if not self.gnome_proxy.apply_proxy(self._proxy_port()):
                    self.pm.stop()
                    QMessageBox.critical(
                        self,
                        "GNOME Proxy Error",
                        "The SOCKS proxy could not be applied safely. "
                        "ByeDPI was stopped.\n\n" + self.gnome_proxy.last_error,
                    )
                    return

        else:
            QMessageBox.warning(self, "Error", "Failed to start process or open port.")

    def stop_process(self):
        self.stop_btn.setEnabled(False)
        self.action_stop.setEnabled(False)
        self.pm.stop()
        self._restore_proxy_with_warning()

    def _restore_proxy_with_warning(self) -> bool:
        if not self.gnome_proxy.has_journal():
            return True
        restored = self.gnome_proxy.restore_proxy()
        if not restored:
            QMessageBox.critical(
                self,
                "Proxy Recovery Failed",
                "GNOME proxy settings were not fully restored. "
                "The recovery journal was retained.\n\n"
                + self.gnome_proxy.last_error,
            )
        return restored

    def _cleanup_and_stop(self):
        self._restore_proxy_with_warning()
        self.pm.stop()

    def check_proxy(self):
        args = self.args_input.text().strip()
        try:
            args_list = shlex.split(args)
        except ValueError:
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
        diag = DiagnosticsDialog(self.binary_path, self)
        diag.run_diagnostics()
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
        # An unexpected ciadpi exit must not leave the desktop proxy active.
        self._restore_proxy_with_warning()

    def closeEvent(self, event):
        self.save_settings()
        if not self._quitting and self.tray_available and self.tray_icon.isVisible():
            event.ignore()
            self.hide()
            if not self._tray_notice_shown:
                self.tray_icon.showMessage(
                    "ByeByeDPI Linux",
                    "The application is still running in the system tray.",
                    QSystemTrayIcon.Information,
                    3000,
                )
                self._tray_notice_shown = True
            return
        self._cleanup_and_stop()
        event.accept()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show()

    def quit_app(self):
        self._quitting = True
        self.save_settings()
        self._cleanup_and_stop()
        self.tray_icon.hide()
        QApplication.quit()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setOrganizationName("ByeByeDPI")
    app.setApplicationName("ByeByeDPI-Linux")

    # Keep running after the window closes only when a real tray is available.
    app.setQuitOnLastWindowClosed(not QSystemTrayIcon.isSystemTrayAvailable())

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
