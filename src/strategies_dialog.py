import json
import os
import csv
import result_bundle
from history_dialog import HistoryDialog
import time
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLineEdit, QLabel, QMessageBox,
    QProgressBar, QAbstractItemView, QTreeWidget, QTreeWidgetItem,
    QSplitter, QFileDialog, QComboBox, QApplication, QCheckBox, QSpinBox
)
from PySide6.QtCore import Qt, QSettings, Signal
from PySide6.QtGui import QGuiApplication
from strategy_tester import StrategyTesterThread

ANDROID_ASSET_PATHS = [
    "app/src/main/assets/proxytest_cloudflare.sites",
    "app/src/main/assets/proxytest_discord.sites",
    "app/src/main/assets/proxytest_general.sites",
    "app/src/main/assets/proxytest_googlevideo.sites",
    "app/src/main/assets/proxytest_social.sites",
    "app/src/main/assets/proxytest_telegram.sites",
    "app/src/main/assets/proxytest_türkiye.sites",
    "app/src/main/assets/proxytest_youtube.sites",
    "app/src/main/assets/proxytest_strategies.list",
]
UPSTREAM_INFO = {
    "android": {
        "repo": "https://github.com/romanvht/ByeByeDPI",
        "commit": "ffda4fa93d94472217c75e51b45fdd18f966c0af",
        "asset_paths": ANDROID_ASSET_PATHS,
    },
    "ciadpi": {
        "repo": "https://github.com/hufrea/byedpi",
        "submodule_commit": "ba532298de7b28cfe854aea83d061369d13ca290",
        "path": "vendor/byedpi",
    },
}
POLICY_INFO = {
    "method": "GET",
    "follow_redirects": True,
    "remote_dns": "SOCKS5 hostname",
    "connection_header": "close",
    "connect_timeout_seconds": 5,
    "process_timeout_seconds": 10,
    "success_semantics": "curl exit code 0; any HTTP status is network success",
    "response_content_saved": False,
}

class StrategyDetailsDialog(QDialog):
    def __init__(self, strategy_id, results, targets_dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Details for Strategy: {strategy_id}")
        self.resize(800, 600)
        self.results = results
        self.targets_dict = targets_dict
        layout = QVBoxLayout(self)

        # Filters
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Status:"))
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All", "Passed", "Failed", "Timeout", "Error"])
        self.status_filter.currentTextChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.status_filter)

        filter_layout.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search domain or group...")
        self.search_input.textChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.search_input)

        self.btn_copy = QPushButton("Copy Selected")
        self.btn_copy.clicked.connect(self.copy_selected)
        filter_layout.addWidget(self.btn_copy)

        layout.addLayout(filter_layout)

        # Summary Label
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        # Table
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Group", "Host/URL", "Status", "HTTP Code", "Time (s)", "Error"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table)

        self.populate_data()

    def populate_data(self):
        self.table.setRowCount(len(self.results))
        counts = {"All": 0, "Passed": 0, "Failed": 0, "Timeout": 0, "Error": 0}
        group_counts = {}

        for i, res in enumerate(self.results):
            tid = res["target_id"]
            target = self.targets_dict.get(tid, {})
            group = target.get("group_name", "Unknown")
            host = target.get("host", tid)
            status = res["status"]

            # Count status
            counts["All"] += 1
            if status == "Success":
                counts["Passed"] += 1
            elif status == "Timeout":
                counts["Timeout"] += 1
            else:
                counts["Error"] += 1
                counts["Failed"] += 1

            # Count groups
            if group not in group_counts:
                group_counts[group] = {"passed": 0, "total": 0}
            group_counts[group]["total"] += 1
            if status == "Success":
                group_counts[group]["passed"] += 1

            self.table.setItem(i, 0, QTableWidgetItem(group))
            self.table.setItem(i, 1, QTableWidgetItem(host))
            self.table.setItem(i, 2, QTableWidgetItem(status))
            self.table.setItem(i, 3, QTableWidgetItem(res.get("http_code", "")))
            self.table.setItem(i, 4, QTableWidgetItem(f"{res.get('duration', 0):.2f}"))
            self.table.setItem(i, 5, QTableWidgetItem(res.get("error_msg", "")))

        group_summary = " | ".join([f"{g}: {c['passed']}/{c['total']}" for g, c in group_counts.items()])
        summary_text = (f"Total: {counts['All']} | Passed: {counts['Passed']} | Timeout: {counts['Timeout']} | Error: {counts['Error']}\n"
                        f"Groups: {group_summary}")
        self.summary_label.setText(summary_text)

    def apply_filters(self):
        status = self.status_filter.currentText()
        search_text = self.search_input.text().lower()

        for i in range(self.table.rowCount()):
            match_status = True
            row_status = self.table.item(i, 2).text()
            if status == "Passed" and row_status != "Success":
                match_status = False
            elif status == "Timeout" and row_status != "Timeout":
                match_status = False
            elif status == "Error" and row_status != "Error":
                match_status = False
            elif status == "Failed" and row_status == "Success":
                match_status = False

            match_search = False
            for j in range(self.table.columnCount()):
                item = self.table.item(i, j)
                if item and search_text in item.text().lower():
                    match_search = True
                    break

            self.table.setRowHidden(i, not (match_status and match_search))

    def copy_selected(self):
        selected_ranges = self.table.selectedRanges()
        if not selected_ranges:
            return

        texts = []
        for r in selected_ranges:
            for i in range(r.topRow(), r.bottomRow() + 1):
                if not self.table.isRowHidden(i):
                    row_data = [self.table.item(i, j).text() for j in range(self.table.columnCount()) if self.table.item(i, j)]
                    texts.append("\t".join(row_data))

        clipboard = QGuiApplication.clipboard()
        clipboard.setText("\n".join(texts))

class StrategiesDialog(QDialog):
    COL_FAV = 0
    COL_RANK = 1
    COL_ID = 2
    COL_NAME = 3
    COL_PASSED = 4
    COL_TOTAL = 5
    COL_PCT = 6
    COL_AVG = 7
    COL_MEDIAN = 8
    COL_ERR = 9
    COL_STATUS = 10
    strategy_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Strategies Library")
        self.resize(1100, 700)
        self.settings = QSettings("ByeByeDPI", "ByeByeDPI-Linux")

        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.strategies_file = os.path.join(self.base_dir, "data", "strategies.json")
        self.targets_file = os.path.join(self.base_dir, "data", "test_targets.json")
        self.strategies = []
        self.target_groups = []
        self.targets_dict = {}
        self.test_results = {} # strategy_id -> list of target results
        self.is_paused = False

        self.load_data()
        self.favorites = self._load_favorites()
        self.tester_thread = None
        self.init_ui()
        self._restore_dialog_settings()

    def _load_favorites(self) -> list:
        raw_favorites = self.settings.value("favorites_strategies", [])
        if raw_favorites is None:
            candidates = []
        elif isinstance(raw_favorites, str):
            candidates = [raw_favorites]
        elif isinstance(raw_favorites, (list, tuple)):
            candidates = list(raw_favorites)
        else:
            candidates = []

        valid_ids = {s.get("id") for s in self.strategies if s.get("id")}
        normalized = []
        for favorite in candidates:
            if isinstance(favorite, str) and favorite in valid_ids and favorite not in normalized:
                normalized.append(favorite)

        if candidates != normalized or not isinstance(raw_favorites, list):
            self.settings.setValue("favorites_strategies", normalized)
        return normalized

    def load_data(self):
        self.strategies = []
        self.target_groups = []
        self.targets_dict = {}
        if os.path.exists(self.strategies_file):
            try:
                with open(self.strategies_file, 'r', encoding='utf-8') as f:
                    self.strategies = json.load(f).get("strategies", [])
            except Exception as e:
                print(f"Error loading strategies: {e}")

        if os.path.exists(self.targets_file):
            try:
                with open(self.targets_file, 'r', encoding='utf-8') as f:
                    self.target_groups = json.load(f).get("groups", [])
                    for g in self.target_groups:
                        for t in g.get("targets", []):
                            t["group_name"] = g["group_name"]
                            self.targets_dict[t["target_id"]] = t
            except Exception as e:
                print(f"Error loading targets: {e}")

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)

        # --- LEFT PANE (Targets) ---
        left_widget = QDialog()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_layout.addWidget(QLabel("Test Targets:"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.populate_tree()
        left_layout.addWidget(self.tree)

        tree_btn_layout = QHBoxLayout()
        btn_all = QPushButton("All")
        btn_all.clicked.connect(lambda: self.set_tree_checked(Qt.Checked))
        btn_none = QPushButton("None")
        btn_none.clicked.connect(lambda: self.set_tree_checked(Qt.Unchecked))
        btn_def = QPushButton("Default")
        btn_def.clicked.connect(lambda: self.populate_tree(use_saved=False))
        tree_btn_layout.addWidget(btn_all)
        tree_btn_layout.addWidget(btn_none)
        tree_btn_layout.addWidget(btn_def)
        left_layout.addLayout(tree_btn_layout)

        tree_io_layout = QHBoxLayout()
        btn_import = QPushButton("Import")
        btn_import.clicked.connect(self.import_targets)
        btn_export = QPushButton("Export")
        btn_export.clicked.connect(self.export_targets)
        tree_io_layout.addWidget(btn_import)
        tree_io_layout.addWidget(btn_export)
        left_layout.addLayout(tree_io_layout)

        # --- RIGHT PANE (Strategies) ---
        right_widget = QDialog()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.textChanged.connect(self.filter_table)
        search_layout.addWidget(self.search_input)
        self.chk_fav_only = QCheckBox("Favorites Only")
        self.chk_fav_only.toggled.connect(self.filter_table)
        search_layout.addWidget(self.chk_fav_only)
        right_layout.addLayout(search_layout)

        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels(["★", "Rank", "ID", "Name", "Passed", "Total", "%", "Avg", "Median", "Err", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(self.COL_NAME, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_FAV, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(self.show_details)
        self.populate_table()
        right_layout.addWidget(self.table)

        self.progress_label = QLabel("")
        self.eta_label = QLabel("")
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)

        prog_layout = QHBoxLayout()
        prog_layout.addWidget(self.progress_label)
        prog_layout.addWidget(self.eta_label)
        prog_layout.addWidget(self.progress_bar)
        right_layout.addLayout(prog_layout)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([300, 800])
        main_layout.addWidget(splitter)

        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_test_selected = QPushButton("Test Selected")
        self.btn_test_selected.clicked.connect(self.test_selected)
        btn_layout.addWidget(self.btn_test_selected)

        self.btn_test_all = QPushButton("Test All")
        self.btn_test_all.clicked.connect(self.test_all)
        btn_layout.addWidget(self.btn_test_all)

        self.btn_pause = QPushButton("Pause")
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_pause.setEnabled(False)
        btn_layout.addWidget(self.btn_pause)

        self.btn_stop_test = QPushButton("Stop Test")
        self.btn_stop_test.clicked.connect(self.stop_test)
        self.btn_stop_test.setEnabled(False)
        btn_layout.addWidget(self.btn_stop_test)

        self.btn_select_best = QPushButton("Select Best")
        self.btn_select_best.clicked.connect(self.select_best)
        btn_layout.addWidget(self.btn_select_best)

        self.btn_select_best_fav = QPushButton("Select Best Favorite")
        self.btn_select_best_fav.clicked.connect(self.select_best_favorite)
        btn_layout.addWidget(self.btn_select_best_fav)

        self.btn_export_res = QPushButton("Export Results")
        self.btn_export_res.clicked.connect(self.export_results)
        btn_layout.addWidget(self.btn_export_res)

        self.btn_import_res = QPushButton("Import Results")
        self.btn_import_res.clicked.connect(self.import_results)
        btn_layout.addWidget(self.btn_import_res)

        self.btn_history = QPushButton("History")
        self.btn_history.clicked.connect(self.open_history)
        btn_layout.addWidget(self.btn_history)

        self.btn_updates = QPushButton("Updates…")
        self.btn_updates.clicked.connect(self.open_update_center)
        btn_layout.addWidget(self.btn_updates)

        self.chk_autosave = QCheckBox("Auto-save History")
        self.chk_autosave.setChecked(
            self.settings.value("strategies/autosave_history", True, type=bool)
        )
        self.chk_autosave.toggled.connect(
            lambda value: self.settings.setValue("strategies/autosave_history", value)
        )
        btn_layout.addWidget(self.chk_autosave)

        btn_layout.addWidget(QLabel("Connect timeout:"))
        self.connect_timeout_spin = QSpinBox()
        self.connect_timeout_spin.setRange(1, 60)
        self.connect_timeout_spin.setSuffix(" s")
        self.connect_timeout_spin.setValue(
            self.settings.value("strategies/connect_timeout", 5, type=int)
        )
        btn_layout.addWidget(self.connect_timeout_spin)

        btn_layout.addWidget(QLabel("Total timeout:"))
        self.total_timeout_spin = QSpinBox()
        self.total_timeout_spin.setRange(1, 120)
        self.total_timeout_spin.setSuffix(" s")
        self.total_timeout_spin.setValue(
            self.settings.value("strategies/total_timeout", 10, type=int)
        )
        self.total_timeout_spin.setMinimum(self.connect_timeout_spin.value())
        self.connect_timeout_spin.valueChanged.connect(
            self.total_timeout_spin.setMinimum
        )
        btn_layout.addWidget(self.total_timeout_spin)

        btn_layout.addStretch()

        self.btn_apply = QPushButton("Apply Selected")
        self.btn_apply.clicked.connect(self.apply_selected)
        btn_layout.addWidget(self.btn_apply)
        main_layout.addLayout(btn_layout)

    def populate_tree(self, use_saved=True):
        self.tree.clear()
        for g in self.target_groups:
            g_item = QTreeWidgetItem(self.tree)
            g_item.setText(0, f"{g['group_name']} ({len(g['targets'])})")
            g_item.setFlags(g_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)

            check_state = Qt.Checked if g.get("enabled_by_default") else Qt.Unchecked
            g_item.setCheckState(0, check_state)

            for t in g["targets"]:
                t_item = QTreeWidgetItem(g_item)
                t_item.setText(0, t["host"])
                t_item.setData(0, Qt.UserRole, t)
                t_item.setFlags(t_item.flags() | Qt.ItemIsUserCheckable)
                t_item.setCheckState(0, check_state)

        if use_saved and self.settings.contains("strategies/selected_target_ids"):
            self._apply_saved_target_selection()

    def _apply_saved_target_selection(self):
        saved = self.settings.value("strategies/selected_target_ids", [])
        if isinstance(saved, str):
            saved = [saved]
        saved_ids = {str(target_id) for target_id in saved}
        for index in range(self.tree.topLevelItemCount()):
            group_item = self.tree.topLevelItem(index)
            for child_index in range(group_item.childCount()):
                child = group_item.child(child_index)
                target = child.data(0, Qt.UserRole) or {}
                child.setCheckState(
                    0,
                    Qt.Checked if str(target.get("target_id")) in saved_ids else Qt.Unchecked,
                )

    def _restore_dialog_settings(self):
        geometry = self.settings.value("strategies/geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def save_dialog_settings(self):
        favs = []
        for i in range(self.table.rowCount()):
            if self.table.item(i, self.COL_FAV).checkState() == Qt.Checked:
                favs.append(self.table.item(i, self.COL_ID).text())
        self.settings.setValue("favorites_strategies", favs)

        selected_ids = [target["target_id"] for target in self.get_selected_targets()]
        self.settings.setValue("strategies/geometry", self.saveGeometry())
        self.settings.setValue("strategies/selected_target_ids", selected_ids)
        self.settings.setValue("strategies/autosave_history", self.chk_autosave.isChecked())
        self.settings.setValue("strategies/connect_timeout", self.connect_timeout_spin.value())
        self.settings.setValue("strategies/total_timeout", self.total_timeout_spin.value())
        self.settings.sync()

    def _policy_info(self):
        policy = dict(POLICY_INFO)
        policy["connect_timeout_seconds"] = self.connect_timeout_spin.value()
        policy["process_timeout_seconds"] = self.total_timeout_spin.value()
        return policy

    def set_tree_checked(self, state):
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, state)

    def get_selected_targets(self):
        targets = []
        for i in range(self.tree.topLevelItemCount()):
            g_item = self.tree.topLevelItem(i)
            for j in range(g_item.childCount()):
                t_item = g_item.child(j)
                if t_item.checkState(0) == Qt.Checked:
                    targets.append(t_item.data(0, Qt.UserRole))
        return targets

    def populate_table(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.strategies))
        favs = self._load_favorites()
        self.favorites = favs
        for i, s in enumerate(self.strategies):
            sid = s.get("id", "")

            fav_item = QTableWidgetItem()
            fav_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            fav_item.setCheckState(Qt.Checked if sid in favs else Qt.Unchecked)
            self.table.setItem(i, self.COL_FAV, fav_item)

            self.table.setItem(i, self.COL_RANK, QTableWidgetItem(""))
            self.table.setItem(i, self.COL_ID, QTableWidgetItem(sid))
            self.table.setItem(i, self.COL_NAME, QTableWidgetItem(s.get("name", "")))
            self.table.setItem(i, self.COL_PASSED, QTableWidgetItem("-"))
            self.table.setItem(i, self.COL_TOTAL, QTableWidgetItem("-"))
            self.table.setItem(i, self.COL_PCT, QTableWidgetItem("-"))
            self.table.setItem(i, self.COL_AVG, QTableWidgetItem("-"))
            self.table.setItem(i, self.COL_MEDIAN, QTableWidgetItem("-"))
            self.table.setItem(i, self.COL_ERR, QTableWidgetItem("-"))
            self.table.setItem(i, self.COL_STATUS, QTableWidgetItem("Ready"))
        self.table.setSortingEnabled(True)

    def filter_table(self, text=None):
        if text is None or isinstance(text, bool):
            text = self.search_input.text()
        text = text.lower()
        fav_only = self.chk_fav_only.isChecked()
        for i in range(self.table.rowCount()):
            match_search = False
            for j in range(1, self.table.columnCount()):
                item = self.table.item(i, j)
                if item and text in item.text().lower():
                    match_search = True
                    break

            match_fav = True
            if fav_only:
                match_fav = self.table.item(i, self.COL_FAV).checkState() == Qt.Checked

            self.table.setRowHidden(i, not (match_search and match_fav))

    def test_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No selection", "Please select a strategy to test.")
            return

        strategy_id = self.table.item(row, self.COL_ID).text()
        strategy = next((s for s in self.strategies if s["id"] == strategy_id), None)
        if strategy:
            self.start_tester([strategy])

    def test_all(self):
        self.start_tester(self.strategies)

    def start_tester(self, strategies_to_test):
        targets = self.get_selected_targets()
        if not targets:
            QMessageBox.warning(self, "Error", "No targets selected.")
            return

        total_runs = len(strategies_to_test) * len(targets)

        # Show warning if large run (skip warning in test mode if running without real DISPLAY)
        if total_runs > 3000 and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            reply = QMessageBox.question(self, "Large Test Run", f"You are about to start {total_runs} tests.\nThis may take a while and cause network load.\nContinue?", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No: return

        self.btn_test_selected.setEnabled(False)
        self.btn_test_all.setEnabled(False)
        self.btn_stop_test.setEnabled(True)
        self.btn_pause.setEnabled(True)
        self.btn_pause.setText("Pause")
        self.is_paused = False

        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(total_runs)
        self.progress_bar.setValue(0)
        self.test_results.clear()

        self.run_start_time = time.time()
        self.completed_runs = 0

        # Reset states for testing strategies
        for s in strategies_to_test:
            for i in range(self.table.rowCount()):
                if self.table.item(i, self.COL_ID).text() == s["id"]:
                    self.table.setItem(i, self.COL_STATUS, QTableWidgetItem("Testing..."))

        self.tester_thread = StrategyTesterThread(
            strategies_to_test,
            targets,
            connect_timeout=self.connect_timeout_spin.value(),
            total_timeout=self.total_timeout_spin.value(),
        )
        self.tester_thread.progress.connect(self.update_progress)
        self.tester_thread.strategy_started.connect(self.on_strategy_started)
        self.tester_thread.target_result.connect(self.on_target_result)
        self.tester_thread.strategy_finished.connect(self.on_strategy_finished)
        self.tester_thread.finished.connect(self.on_tester_finished)
        self.tester_thread.start()

    def toggle_pause(self):
        if not self.tester_thread:
            return
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.btn_pause.setText("Resume")
            self.progress_label.setText("Pausing after current check...")
            self.tester_thread.pause()
        else:
            self.btn_pause.setText("Pause")
            self.tester_thread.resume()

    def update_progress(self, s_idx, s_total, t_idx, t_total):
        if not self.run_start_time:
            self.run_start_time = time.time()

        current_global = s_idx * t_total + t_idx
        self.progress_bar.setValue(current_global)

        if not self.is_paused:
            self.progress_label.setText(f"Strategy {s_idx+1}/{s_total}, Target {t_idx+1}/{t_total}")

        # Calc ETA
        self.completed_runs = current_global
        if self.completed_runs > 5:
            elapsed = time.time() - self.run_start_time
            avg_sec = elapsed / self.completed_runs
            remains = self.progress_bar.maximum() - self.completed_runs
            eta_sec = int(remains * avg_sec)
            self.eta_label.setText(f"ETA: {eta_sec}s")
        else:
            self.eta_label.setText("ETA: calculating...")

    def on_strategy_started(self, strategy_id):
        self.test_results[strategy_id] = []
        for i in range(self.table.rowCount()):
            if self.table.item(i, self.COL_ID).text() == strategy_id:
                self.table.setItem(i, self.COL_STATUS, QTableWidgetItem("Running..."))
                break

    def on_target_result(self, strategy_id, target_id, status, duration, http_code, error_msg):
        if strategy_id in self.test_results:
            self.test_results[strategy_id].append({
                "target_id": target_id,
                "status": status,
                "duration": duration,
                "http_code": http_code,
                "error_msg": error_msg
            })

    def on_strategy_finished(self, strategy_id, passed, total, avg_time, median_time, timeout, error):
        try:
            self.table.setSortingEnabled(False)
            for i in range(self.table.rowCount()):
                if self.table.item(i, self.COL_ID).text() == strategy_id:
                    pct = (passed / total * 100) if total > 0 else 0
                    self.table.setItem(i, self.COL_PASSED, QTableWidgetItem(str(passed)))

                    item_pct = QTableWidgetItem(f"{pct:.1f}%")
                    item_pct.setData(Qt.UserRole, pct)
                    self.table.setItem(i, self.COL_PCT, item_pct)

                    item_avg = QTableWidgetItem(f"{avg_time:.2f}")
                    item_avg.setData(Qt.UserRole, avg_time)
                    self.table.setItem(i, self.COL_AVG, item_avg)

                    item_med = QTableWidgetItem(f"{median_time:.2f}")
                    item_med.setData(Qt.UserRole, median_time)
                    self.table.setItem(i, self.COL_MEDIAN, item_med)

                    self.table.setItem(i, self.COL_TOTAL, QTableWidgetItem(str(total)))
                    self.table.setItem(i, self.COL_ERR, QTableWidgetItem(str(timeout + error)))
                    self.table.setItem(i, self.COL_STATUS, QTableWidgetItem("Done"))
                    break
            self.table.setSortingEnabled(True)
            self.update_ranks()
        except Exception as e:
            print(f"Exception in on_strategy_finished: {e}")

    def stop_test(self):
        if self.tester_thread:
            self.tester_thread.cancel()
            self.btn_stop_test.setEnabled(False)

    def on_tester_finished(self):
        self.btn_test_selected.setEnabled(True)
        self.btn_test_all.setEnabled(True)
        self.btn_stop_test.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.progress_label.setText("Finished")
        self.eta_label.setText("")

        self.tester_thread = None
        self.update_ranks()

        try:
            if hasattr(self, 'chk_autosave') and self.chk_autosave.isChecked():
                bundle = result_bundle.create_bundle(
                    self.strategies, self.get_selected_targets(), self.test_results,
                    getattr(self, "run_start_time", 0), time.time(), "completed",
                    len([s for s in self.strategies if s["id"] in self.test_results]),
                    len(self.get_selected_targets()),
                    self.progress_bar.maximum() if hasattr(self, "progress_bar") else 0,
                    self.completed_runs if hasattr(self, "completed_runs") else 0,
                    UPSTREAM_INFO,
                    self._policy_info()
                )
                result_bundle.save_to_history(bundle)
        except Exception as e:
            print(f"History save failed: {e}")


    def open_update_center(self):
        if self.tester_thread is not None:
            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                QMessageBox.warning(
                    self,
                    "Test in Progress",
                    "Stop the current strategy test before updating data files.",
                )
            return
        from update_dialog import UpdateDialog

        dialog = UpdateDialog(os.path.join(self.base_dir, "data"), self)
        dialog.data_updated.connect(self.reload_updated_data)
        dialog.exec()

    def reload_updated_data(self, _kind=None):
        selected_ids = {
            target["target_id"] for target in self.get_selected_targets()
        }
        self.settings.setValue("strategies/selected_target_ids", sorted(selected_ids))
        self.settings.sync()
        self.load_data()
        self.populate_tree(use_saved=True)
        self.populate_table()
        self.test_results.clear()
        self.progress_bar.setValue(0)
        self.progress_label.setText("Ready")
        self.eta_label.setText("")

    def open_history(self):
        dlg = HistoryDialog(self)
        if dlg.exec():
            if dlg.opened_filepath:
                try:
                    bundle, warnings = result_bundle.load_bundle(dlg.opened_filepath)
                    self.test_results = bundle.get("results", {})

                    if warnings and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                        QMessageBox.warning(self, "Import Warnings", "\n".join(warnings))

                    for strat_id, agg in bundle.get("aggregates", {}).get("strategies", {}).items():
                        self.on_strategy_finished(strat_id, agg["passed"], agg["total"], agg["avg_time"], agg["median_time"], agg["timeouts"], agg["errors"])

                    if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                        QMessageBox.information(self, "Success", "Results loaded from history.")
                except Exception as e:
                    if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                        QMessageBox.critical(self, "Error", f"Failed to load history: {e}")

    def update_ranks(self):
        rows = []
        for i in range(self.table.rowCount()):
            passed_str = self.table.item(i, self.COL_PASSED).text()
            passed = int(passed_str) if passed_str.isdigit() else -1

            pct_item = self.table.item(i, self.COL_PCT)
            pct = pct_item.data(Qt.UserRole) if pct_item and pct_item.data(Qt.UserRole) is not None else -1

            med_item = self.table.item(i, self.COL_MEDIAN)
            med_time = med_item.data(Qt.UserRole) if med_item and med_item.data(Qt.UserRole) is not None else 9999

            err_str = self.table.item(i, self.COL_ERR).text()
            errs = int(err_str) if err_str.isdigit() else 9999

            id_val = self.table.item(i, self.COL_ID).text()
            rows.append((-passed, -pct, med_time, errs, i, id_val))

        rows.sort()

        self.table.setSortingEnabled(False)
        for rank, (neg_p, neg_pct, med_t, errs, orig_idx, id_val) in enumerate(rows):
            for i in range(self.table.rowCount()):
                if self.table.item(i, self.COL_ID).text() == id_val:
                    if neg_p <= 0:
                        self.table.setItem(i, self.COL_RANK, QTableWidgetItem(str(rank + 1)))
                    break
        self.table.setSortingEnabled(True)

    def select_best(self):
        self._select_best_by_filter(fav_only=False)

    def select_best_favorite(self):
        self._select_best_by_filter(fav_only=True)

    def _select_best_by_filter(self, fav_only=False):
        best_row = -1
        best_rank = 9999
        for i in range(self.table.rowCount()):
            if self.table.isRowHidden(i): continue
            if fav_only and self.table.item(i, self.COL_FAV).checkState() != Qt.Checked: continue

            rank_str = self.table.item(i, self.COL_RANK).text()
            if rank_str.isdigit():
                if int(rank_str) < best_rank:
                    best_rank = int(rank_str)
                    best_row = i

        if best_row >= 0:
            self.table.selectRow(best_row)
        else:
            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                msg = "No favorite success found." if fav_only else "No successful strategy found."
                QMessageBox.information(self, "No Results", msg)

    def show_details(self, index):
        row = index.row()
        strategy_id = self.table.item(row, self.COL_ID).text()
        if strategy_id in self.test_results:
            dlg = StrategyDetailsDialog(strategy_id, self.test_results[strategy_id], self.targets_dict, self)
            dlg.show()
            QApplication.processEvents()

    def apply_selected(self):
        row = self.table.currentRow()
        if row < 0:
            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                QMessageBox.warning(self, "No selection", "Please select a strategy to apply.")
            return

        strategy_id = self.table.item(row, self.COL_ID).text()
        strategy = next((s for s in self.strategies if s["id"] == strategy_id), None)
        if strategy:
            self.strategy_selected.emit(strategy["args"])
            self.accept()

    def export_results(self):
        if not self.test_results:
            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                QMessageBox.warning(self, "No data", "No test results to export.")
            return

        filename, filter_used = QFileDialog.getSaveFileName(self, "Export Results", "results", "JSON Files (*.json);;CSV Flat (*.csv);;CSV Summary (*.csv)")
        if not filename: return

        bundle = result_bundle.create_bundle(
            self.strategies, self.get_selected_targets(), self.test_results,
            getattr(self, "run_start_time", 0), time.time(),
            "completed" if getattr(self, "tester_thread", None) is None else "partial",
            len(set(s["id"] for s in self.strategies if s["id"] in self.test_results)),
            len(self.get_selected_targets()),
            self.progress_bar.maximum() if hasattr(self, "progress_bar") else 0,
            self.completed_runs if hasattr(self, "completed_runs") else 0,
            UPSTREAM_INFO,
            self._policy_info()
        )

        try:
            if filter_used == "CSV Flat (*.csv)":
                result_bundle.export_csv_flat(bundle, filename)
            elif filter_used == "CSV Summary (*.csv)":
                result_bundle.export_csv_summary(bundle, filename)
            else:
                result_bundle.save_bundle(filename, bundle)

            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                QMessageBox.information(self, "Success", "Export completed.")
        except Exception as e:
            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                QMessageBox.critical(self, "Error", str(e))

    def import_results(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Import Results", "", "JSON Files (*.json)")
        if not filename: return

        try:
            bundle, warnings = result_bundle.load_bundle(filename)
            self.test_results = bundle.get("results", {})

            if warnings and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                QMessageBox.warning(self, "Import Warnings", "\\n".join(warnings))

            for strat_id, agg in bundle.get("aggregates", {}).get("strategies", {}).items():
                self.on_strategy_finished(strat_id, agg["passed"], agg["total"], agg["avg_time"], agg["median_time"], agg["timeouts"], agg["errors"])

            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                QMessageBox.information(self, "Success", "Results imported.")
        except Exception as e:
            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                QMessageBox.critical(self, "Error", f"Import failed: {e}")

    def import_targets(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Import Targets JSON", "", "JSON Files (*.json)")
        if not filename:
            return
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
                new_groups = data.get("groups", [])
                if not new_groups:
                    raise ValueError("No groups found in JSON")

                # Check for duplicates or merge
                for g in new_groups:
                    if not any(eg["group_id"] == g["group_id"] for eg in self.target_groups):
                        self.target_groups.append(g)
                    for t in g.get("targets", []):
                        t["group_name"] = g["group_name"]
                        self.targets_dict[t["target_id"]] = t

                self.populate_tree()
                if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                    QMessageBox.information(self, "Success", "Targets imported successfully.")
        except Exception as e:
            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                QMessageBox.warning(self, "Import Failed", f"Failed to import targets: {str(e)}")

    def export_targets(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Export Targets JSON", "custom_targets.json", "JSON Files (*.json)")
        if not filename:
            return
        try:
            data = {
                "metadata": {"total_groups": len(self.target_groups)},
                "groups": self.target_groups
            }
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                QMessageBox.information(self, "Success", "Targets exported successfully.")
        except Exception as e:
            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                QMessageBox.warning(self, "Export Failed", f"Failed to export targets: {str(e)}")

    def closeEvent(self, event):
        self.save_dialog_settings()
        self.stop_test()
        super().closeEvent(event)
