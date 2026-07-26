import json
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLineEdit, QLabel, QMessageBox,
    QProgressBar, QAbstractItemView
)
from PySide6.QtCore import Qt, Signal
from strategy_tester import StrategyTesterThread

class StrategiesDialog(QDialog):
    strategy_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Strategies Library")
        self.resize(800, 600)

        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.strategies_file = os.path.join(self.base_dir, "data", "strategies.json")
        self.strategies = []
        self.load_strategies()

        self.tester_thread = None

        self.init_ui()

    def load_strategies(self):
        if not os.path.exists(self.strategies_file):
            return
        try:
            with open(self.strategies_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.strategies = data.get("strategies", [])
        except Exception as e:
            print(f"Error loading strategies: {e}")

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Search box
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.textChanged.connect(self.filter_table)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "Name", "Arguments", "Supported", "Test Result"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setSortingEnabled(True)
        self.populate_table()
        layout.addWidget(self.table)

        # Test URL
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("Test URL:"))
        self.url_input = QLineEdit("https://www.google.com")
        url_layout.addWidget(self.url_input)
        layout.addLayout(url_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Buttons
        btn_layout = QHBoxLayout()
        
        self.btn_test_selected = QPushButton("Test Selected")
        self.btn_test_selected.clicked.connect(self.test_selected)
        btn_layout.addWidget(self.btn_test_selected)

        self.btn_test_all = QPushButton("Test All")
        self.btn_test_all.clicked.connect(self.test_all)
        btn_layout.addWidget(self.btn_test_all)

        self.btn_stop_test = QPushButton("Stop Test")
        self.btn_stop_test.clicked.connect(self.stop_test)
        self.btn_stop_test.setEnabled(False)
        btn_layout.addWidget(self.btn_stop_test)

        self.btn_select_best = QPushButton("Select Best")
        self.btn_select_best.clicked.connect(self.select_best)
        btn_layout.addWidget(self.btn_select_best)
        
        btn_layout.addStretch()

        self.btn_apply = QPushButton("Apply Selected")
        self.btn_apply.clicked.connect(self.apply_selected)
        btn_layout.addWidget(self.btn_apply)

        layout.addLayout(btn_layout)

    def populate_table(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.strategies))
        for i, s in enumerate(self.strategies):
            self.table.setItem(i, 0, QTableWidgetItem(s.get("id", "")))
            self.table.setItem(i, 1, QTableWidgetItem(s.get("name", "")))
            self.table.setItem(i, 2, QTableWidgetItem(s.get("args", "")))
            self.table.setItem(i, 3, QTableWidgetItem("Yes" if s.get("supported") else "No"))
            self.table.setItem(i, 4, QTableWidgetItem(""))
        self.table.setSortingEnabled(True)

    def filter_table(self, text):
        for i in range(self.table.rowCount()):
            match = False
            for j in range(self.table.columnCount()):
                item = self.table.item(i, j)
                if item and text.lower() in item.text().lower():
                    match = True
                    break
            self.table.setRowHidden(i, not match)

    def test_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No selection", "Please select a strategy to test.")
            return
        
        strategy_id = self.table.item(row, 0).text()
        strategy = next((s for s in self.strategies if s["id"] == strategy_id), None)
        if strategy:
            self.start_tester([strategy])

    def test_all(self):
        self.start_tester(self.strategies)

    def start_tester(self, strategies_to_test):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Error", "Test URL cannot be empty.")
            return

        self.btn_test_selected.setEnabled(False)
        self.btn_test_all.setEnabled(False)
        self.btn_stop_test.setEnabled(True)
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(strategies_to_test))
        self.progress_bar.setValue(0)

        # Clear previous results
        for s in strategies_to_test:
            for i in range(self.table.rowCount()):
                if self.table.item(i, 0).text() == s["id"]:
                    self.table.setItem(i, 4, QTableWidgetItem("Testing..."))

        self.tester_thread = StrategyTesterThread(strategies_to_test, url)
        self.tester_thread.progress.connect(self.update_progress)
        self.tester_thread.result.connect(self.update_result)
        self.tester_thread.finished.connect(self.on_tester_finished)
        self.tester_thread.start()

    def update_progress(self, current, total):
        self.progress_bar.setValue(current)

    def update_result(self, strategy_id, status, duration, http_code):
        result_text = f"{status} ({duration:.2f}s) {http_code}".strip()
        for i in range(self.table.rowCount()):
            if self.table.item(i, 0).text() == strategy_id:
                self.table.setItem(i, 4, QTableWidgetItem(result_text))
                break

    def stop_test(self):
        if self.tester_thread:
            self.tester_thread.cancel()
            self.btn_stop_test.setEnabled(False)

    def on_tester_finished(self):
        self.btn_test_selected.setEnabled(True)
        self.btn_test_all.setEnabled(True)
        self.btn_stop_test.setEnabled(False)
        self.tester_thread = None

    def select_best(self):
        best_row = -1
        best_duration = float('inf')

        for i in range(self.table.rowCount()):
            result = self.table.item(i, 4).text()
            if result.startswith("Success"):
                # format: "Success (1.23s) 200"
                try:
                    dur_str = result.split('(')[1].split('s')[0]
                    dur = float(dur_str)
                    if dur < best_duration:
                        best_duration = dur
                        best_row = i
                except:
                    pass
        
        if best_row >= 0:
            self.table.selectRow(best_row)
        else:
            QMessageBox.information(self, "No Success", "No successful strategies found.")

    def apply_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No selection", "Please select a strategy to apply.")
            return
        
        args = self.table.item(row, 2).text()
        self.strategy_selected.emit(args)
        self.accept()

    def closeEvent(self, event):
        self.stop_test()
        super().closeEvent(event)
