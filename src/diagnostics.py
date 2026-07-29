import os
import json
from pathlib import Path
import PySide6
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QFileDialog,
    QMessageBox
)
from PySide6.QtCore import QTimer
from paths import user_config_dir, user_data_dir
from diagnostics_core import run_diagnostics_core, format_txt_report

class DiagnosticsDialog(QDialog):
    def __init__(self, binary_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ByeByeDPI-Linux Diagnostics")
        self.resize(680, 500)
        self.binary_path = binary_path
        self.last_report = None

        layout = QVBoxLayout(self)
        self.info_label = QLabel("Running diagnostics...")
        layout.addWidget(self.info_label)

        self.report_area = QTextEdit()
        self.report_area.setReadOnly(True)
        layout.addWidget(self.report_area)

        buttons = QHBoxLayout()

        self.run_btn = QPushButton("Run Again")
        self.run_btn.clicked.connect(self.run_diagnostics)
        buttons.addWidget(self.run_btn)

        self.copy_btn = QPushButton("Copy Report")
        self.copy_btn.clicked.connect(self.copy_report)
        buttons.addWidget(self.copy_btn)

        self.save_btn = QPushButton("Save Report...")
        self.save_btn.clicked.connect(self.save_report)
        buttons.addWidget(self.save_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

    def run_diagnostics(self):
        self.info_label.setText("Running diagnostics...")
        self.info_label.setStyleSheet("")
        self.report_area.clear()

        # Use QTimer to not freeze UI on start
        QTimer.singleShot(50, self._do_run)

    def _do_run(self):
        data_dir = user_data_dir(create=False)
        config_dir = user_config_dir(create=False)
        report = run_diagnostics_core(
            self.binary_path,
            data_dir,
            config_dir,
            PySide6.__version__
        )
        self.last_report = report

        txt_report = format_txt_report(report)
        self.report_area.setPlainText(txt_report)

        if report["status"] == "FAIL":
            self.info_label.setText("Some required checks failed.")
            self.info_label.setStyleSheet("color: red; font-weight: bold;")
        elif report["status"] == "WARN":
            self.info_label.setText("Required checks passed with warnings.")
            self.info_label.setStyleSheet("color: darkorange; font-weight: bold;")
        else:
            self.info_label.setText("All checks passed.")
            self.info_label.setStyleSheet("color: green; font-weight: bold;")

    def copy_report(self):
        QApplication.clipboard().setText(self.report_area.toPlainText())

    def save_report(self):
        if not self.last_report:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Report", "diagnostics_report.json", "JSON Files (*.json);;Text Files (*.txt)")
        if path:
            try:
                if path.endswith(".json"):
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(self.last_report, f, indent=2)
                else:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(format_txt_report(self.last_report))
                QMessageBox.information(self, "Success", "Report saved successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save report: {e}")
