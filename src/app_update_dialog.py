import os
import tempfile
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from app_updater import check_for_updates, download_update, ReleaseInfo, AppUpdaterError
from version import __version__

class CheckUpdateThread(QThread):
    result = Signal(object)
    error = Signal(str)

    def run(self):
        try:
            info = check_for_updates()
            self.result.emit(info)
        except Exception as e:
            self.error.emit(str(e))

class DownloadUpdateThread(QThread):
    success = Signal(str)
    error = Signal(str)

    def __init__(self, release_info, dest_dir):
        super().__init__()
        self.release_info = release_info
        self.dest_dir = dest_dir

    def run(self):
        try:
            path = download_update(self.release_info, self.dest_dir)
            self.success.emit(path)
        except Exception as e:
            self.error.emit(str(e))

class AppUpdateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("App Updates")
        self.resize(500, 400)

        self.layout = QVBoxLayout(self)
        self.status_label = QLabel(f"Current version: {__version__}\nChecking for updates...")
        self.layout.addWidget(self.status_label)

        self.notes_edit = QTextEdit()
        self.notes_edit.setReadOnly(True)
        self.layout.addWidget(self.notes_edit)
        self.notes_edit.hide()

        self.btn_layout = QHBoxLayout()

        self.open_url_btn = QPushButton("Open Release Page")
        self.open_url_btn.clicked.connect(self.open_release_page)
        self.open_url_btn.hide()
        self.btn_layout.addWidget(self.open_url_btn)

        self.download_btn = QPushButton("Download Update")
        self.download_btn.clicked.connect(self.start_download)
        self.download_btn.hide()
        self.btn_layout.addWidget(self.download_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        self.btn_layout.addWidget(self.close_btn)

        self.layout.addLayout(self.btn_layout)

        self.release_info = None
        self.release_url = ""
        self.dest_dir = None
        self.downloader = None

        self.checker = CheckUpdateThread()
        self.checker.result.connect(self.on_check_result)
        self.checker.error.connect(self.on_check_error)
        self.checker.start()

    def on_check_result(self, info: ReleaseInfo | None):
        if info:
            self.release_info = info
            self.status_label.setText(
                f"Current version: {__version__}\n"
                f"New version available: {info.version}"
            )
            self.release_url = info.html_url
            self.notes_edit.setPlainText(info.body)
            self.notes_edit.show()
            self.open_url_btn.show()
            self.download_btn.show()
        else:
            self.status_label.setText(f"Current version: {__version__}\nYou are up to date.")

    def on_check_error(self, err: str):
        self.status_label.setText(f"Current version: {__version__}\nError checking for updates: {err}")

    def open_release_page(self):
        if self.release_url:
            QDesktopServices.openUrl(QUrl(self.release_url))

    def start_download(self):
        reply = QMessageBox.question(
            self, "Confirm Download",
            f"Do you want to download the update {self.release_info.version}?\nIt will be saved to a temporary directory.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.download_btn.setEnabled(False)
        self.dest_dir = tempfile.mkdtemp(prefix="byebyedpi-update-")
        self.status_label.setText(f"Downloading to {self.dest_dir} ...")

        self.downloader = DownloadUpdateThread(self.release_info, self.dest_dir)
        self.downloader.success.connect(self.on_download_success)
        self.downloader.error.connect(self.on_download_error)
        self.downloader.start()

    def on_download_success(self, path: str):
        self.status_label.setText(self.status_label.text() + f"\nDownload successful and verified!")
        msg = f"Update archive has been downloaded and verified to:\n{path}\n\nYou can now extract it and run scripts/install-user.sh to update the application."
        QMessageBox.information(self, "Update Ready", msg)
        self.close()

    def on_download_error(self, err: str):
        self.status_label.setText(self.status_label.text() + f"\nDownload failed: {err}")
        self.download_btn.setEnabled(True)

    def closeEvent(self, event):
        if self.downloader and self.downloader.isRunning():
            QMessageBox.warning(self, "Warning", "Download in progress. Please wait until it completes.")
            event.ignore()
            return
        if self.checker and self.checker.isRunning():
            self.checker.result.disconnect()
            self.checker.error.disconnect()
            self.checker.wait(500)
        event.accept()
