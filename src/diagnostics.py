import os
import shutil
import socket
from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QLabel, QHBoxLayout, QApplication
from PySide6.QtCore import Qt

class DiagnosticsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ByeByeDPI-Linux Diagnostics")
        self.resize(500, 400)
        
        layout = QVBoxLayout(self)
        
        self.info_label = QLabel("Running first-run diagnostics...")
        layout.addWidget(self.info_label)
        
        self.report_area = QTextEdit()
        self.report_area.setReadOnly(True)
        layout.addWidget(self.report_area)
        
        btn_layout = QHBoxLayout()
        self.copy_btn = QPushButton("Copy Report")
        self.copy_btn.clicked.connect(self.copy_report)
        btn_layout.addWidget(self.copy_btn)
        
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.close_btn)
        
        layout.addLayout(btn_layout)
        
    def copy_report(self):
        cb = QApplication.clipboard()
        cb.setText(self.report_area.toPlainText())
        
    def run_diagnostics(self, binary_path):
        report = []
        all_passed = True
        
        report.append("--- Diagnostics Report ---")
        
        # Check ciadpi binary
        if os.path.exists(binary_path):
            report.append(f"[OK] ciadpi binary found at {binary_path}")
            if os.access(binary_path, os.X_OK):
                report.append("[OK] ciadpi is executable")
            else:
                report.append("[FAIL] ciadpi is NOT executable")
                all_passed = False
        else:
            report.append(f"[FAIL] ciadpi binary NOT found at {binary_path}. Did you init the submodule and build it?")
            all_passed = False
            
        # Check curl
        curl_path = shutil.which("curl")
        if curl_path:
            report.append(f"[OK] curl found at {curl_path}")
        else:
            report.append("[FAIL] curl NOT found in PATH")
            all_passed = False
            
        # Check port availability (1080 as default)
        port = 1080
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            s.close()
            report.append(f"[OK] Port {port} is available")
        except OSError:
            report.append(f"[FAIL] Port {port} is already in use")
            all_passed = False
            
        self.report_area.setText("\n".join(report))
        
        if all_passed:
            self.info_label.setText("All checks passed!")
            self.info_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.info_label.setText("Some checks failed. Please review the report.")
            self.info_label.setStyleSheet("color: red; font-weight: bold;")
            
        return all_passed
