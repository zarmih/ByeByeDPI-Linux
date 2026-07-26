import os
import json
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QFileDialog, QAbstractItemView
)
from PySide6.QtGui import QColor
import result_bundle

class HistoryDialog(QDialog):
    def __init__(self, parent=None, test_path=None):
        super().__init__(parent)
        self.setWindowTitle("Run History")
        self.setMinimumSize(700, 400)
        self.test_path = test_path
        self.opened_filepath = None
        
        layout = QVBoxLayout(self)
        
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Date", "State", "Strategies", "Targets", "Best Strategy"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        self.btn_open = QPushButton("Open Results")
        self.btn_export = QPushButton("Export")
        self.btn_compare = QPushButton("Compare")
        self.btn_delete = QPushButton("Delete")
        self.btn_clear = QPushButton("Clear History")
        
        btn_layout.addWidget(self.btn_open)
        btn_layout.addWidget(self.btn_export)
        btn_layout.addWidget(self.btn_compare)
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addWidget(self.btn_clear)
        layout.addLayout(btn_layout)
        
        self.btn_open.clicked.connect(self.on_open)
        self.btn_export.clicked.connect(self.on_export)
        self.btn_compare.clicked.connect(self.on_compare)
        self.btn_delete.clicked.connect(self.on_delete)
        self.btn_clear.clicked.connect(self.on_clear)
        
        self.records = []
        self.load_history()
        
    def load_history(self):
        self.table.setRowCount(0)
        self.records = result_bundle.list_history(self.test_path)
        
        for rec in self.records:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(rec.get("created_at", "")))
            self.table.setItem(row, 1, QTableWidgetItem(rec.get("state", "")))
            self.table.setItem(row, 2, QTableWidgetItem(str(rec.get("strategies", 0))))
            self.table.setItem(row, 3, QTableWidgetItem(str(rec.get("targets", 0))))
            self.table.setItem(row, 4, QTableWidgetItem(str(rec.get("best_strategy_id", ""))))

    def get_selected_record(self):
        rows = self.table.selectedItems()
        if not rows: return None
        return self.records[rows[0].row()]
        
    def on_open(self):
        rec = self.get_selected_record()
        if not rec: return
        self.opened_filepath = rec["filepath"]
        self.accept()
        
    def on_export(self):
        rec = self.get_selected_record()
        if not rec: return
        
        filename, filter_used = QFileDialog.getSaveFileName(self, "Export Results", "results", "JSON Files (*.json);;CSV Flat (*.csv);;CSV Summary (*.csv)")
        if not filename: return
        
        try:
            with open(rec["filepath"], 'r', encoding='utf-8') as f:
                bundle = json.load(f)
            
            if filter_used == "CSV Flat (*.csv)":
                result_bundle.export_csv_flat(bundle, filename)
            elif filter_used == "CSV Summary (*.csv)":
                result_bundle.export_csv_summary(bundle, filename)
            else:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(bundle, f, indent=2, ensure_ascii=False)
            
            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                QMessageBox.information(self, "Success", "Export completed.")
        except Exception as e:
            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                QMessageBox.critical(self, "Error", str(e))
                
    def on_compare(self):
        rows = list(set([item.row() for item in self.table.selectedItems()]))
        if len(rows) != 2:
            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                QMessageBox.warning(self, "Compare", "Please select exactly 2 runs to compare.")
            return
            
        r1 = self.records[rows[0]]
        r2 = self.records[rows[1]]
        
        try:
            with open(r1["filepath"], 'r', encoding='utf-8') as f:
                b1 = json.load(f)
            with open(r2["filepath"], 'r', encoding='utf-8') as f:
                b2 = json.load(f)
            
            if r2["mtime"] > r1["mtime"]:
                b1, b2 = b2, b1
                
            comp = result_bundle.compare_bundles(b1, b2)
            
            dlg = QDialog(self)
            dlg.setWindowTitle("Compare Runs")
            dlg.setMinimumSize(800, 400)
            ly = QVBoxLayout(dlg)
            tb = QTableWidget()
            tb.setColumnCount(8)
            tb.setHorizontalHeaderLabels(["Strategy", "Passed (New)", "Passed (Old)", "Passed Diff", "Success% Diff", "Median Diff", "Rank (New)", "Rank Diff"])
            for c in comp:
                ro = tb.rowCount()
                tb.insertRow(ro)
                tb.setItem(ro, 0, QTableWidgetItem(c["id"]))
                tb.setItem(ro, 1, QTableWidgetItem(str(c["passed1"])))
                tb.setItem(ro, 2, QTableWidgetItem(str(c["passed2"])))
                
                dp = QTableWidgetItem(f"{c['d_passed']:+d}")
                if c["d_passed"] > 0: dp.setForeground(QColor("green"))
                elif c["d_passed"] < 0: dp.setForeground(QColor("red"))
                tb.setItem(ro, 3, dp)
                
                dpct = QTableWidgetItem(f"{c['d_pct']:+.1f}%")
                if c["d_pct"] > 0: dpct.setForeground(QColor("green"))
                elif c["d_pct"] < 0: dpct.setForeground(QColor("red"))
                tb.setItem(ro, 4, dpct)
                
                dmed = QTableWidgetItem(f"{c['d_med']:+.2f}s")
                if c["d_med"] < 0: dmed.setForeground(QColor("green"))
                elif c["d_med"] > 0: dmed.setForeground(QColor("red"))
                tb.setItem(ro, 5, dmed)
                
                tb.setItem(ro, 6, QTableWidgetItem(str(c["rank1"])))
                dr = QTableWidgetItem(f"{c['d_rank']:+d}")
                if c["d_rank"] > 0: dr.setForeground(QColor("green"))
                elif c["d_rank"] < 0: dr.setForeground(QColor("red"))
                tb.setItem(ro, 7, dr)
                
            tb.resizeColumnsToContents()
            ly.addWidget(tb)
            dlg.exec()
            
        except Exception as e:
            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                QMessageBox.critical(self, "Error", f"Compare failed: {e}")

    def on_delete(self):
        rec = self.get_selected_record()
        if not rec: return
        
        reply = QMessageBox.Yes
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            reply = QMessageBox.question(self, "Confirm Delete", "Delete selected run?", QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            result_bundle.delete_history_record(rec["filepath"])
            self.load_history()

    def on_clear(self):
        reply = QMessageBox.Yes
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            reply = QMessageBox.question(self, "Confirm Clear", "Delete all history?", QMessageBox.Yes | QMessageBox.No)
            
        if reply == QMessageBox.Yes:
            result_bundle.clear_history(self.test_path)
            self.load_history()
