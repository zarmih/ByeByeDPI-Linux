import json
import os
import shlex
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

def test_strategies_json_validity():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(base_dir, "data", "strategies.json")

    assert os.path.exists(json_path), "strategies.json not found"

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    strategies = data.get("strategies", [])
    assert len(strategies) == 60, f"Expected 60 strategies, found {len(strategies)}"

    ids = [s["id"] for s in strategies]
    assert len(ids) == len(set(ids)), "IDs are not unique"

    # Check order
    for i, s in enumerate(strategies):
        assert s["id"] == f"strategy_{i+1}", "Order is incorrect"

    # Check shell injection
    for s in strategies:
        args_str = s["args"]
        assert ';' not in args_str, f"Found ; in {s['id']}"
        assert '|' not in args_str, f"Found | in {s['id']}"
        assert '&' not in args_str, f"Found & in {s['id']}"
        assert '$' not in args_str, f"Found $ in {s['id']}"

        args = shlex.split(args_str)
        assert len(args) > 0, "Empty arguments"

def test_targets_json_validity():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(base_dir, "data", "test_targets.json")

    assert os.path.exists(json_path), "test_targets.json not found"

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    groups = data.get("groups", [])
    assert len(groups) == 8, f"Expected 8 groups, found {len(groups)}"

    total_targets = sum(len(g["targets"]) for g in groups)
    assert total_targets == 139, f"Expected 139 targets, found {total_targets}"

    # Ensure youtube and googlevideo are enabled_by_default
    for g in groups:
        if g["group_id"] in ["youtube", "googlevideo"]:
            assert g["enabled_by_default"] == True
        else:
            assert g["enabled_by_default"] == False

def test_strategy_tester_logic():
    from strategy_tester import StrategyTesterThread
    strategies = [
        {"id": "strategy_1", "args": "--fake -1", "supported": True}
    ]
    targets = [
        {"target_id": "test_1", "host": "127.0.0.1", "url": "http://127.0.0.1:0/"}
    ]

    tester = StrategyTesterThread(strategies, targets)

    # Test getting free port
    port = tester.get_free_port()
    assert port > 0

    # Test cancel
    tester.cancel()
    assert tester._is_cancelled == True

def test_select_best_logic():
    from strategies_dialog import StrategiesDialog
    from PySide6.QtWidgets import QTableWidgetItem
    from PySide6.QtCore import Qt

    app = QApplication.instance()
    if not app:
        app = QApplication([])

    dialog = StrategiesDialog()

    # Mock data
    dialog.table.setRowCount(3)
    dialog.table.setSortingEnabled(False)

    for i in range(3):
        for j in range(11):
            if not dialog.table.item(i, j):
                dialog.table.setItem(i, j, QTableWidgetItem(""))

    # Setup ranks and favs
    # Row 0: Fav, no rank (failed)
    chk0 = QTableWidgetItem()
    chk0.setCheckState(Qt.Checked)
    dialog.table.setItem(0, StrategiesDialog.COL_FAV, chk0)
    dialog.table.setItem(0, StrategiesDialog.COL_RANK, QTableWidgetItem(""))

    # Row 1: Fav, Rank 2
    chk1 = QTableWidgetItem()
    chk1.setCheckState(Qt.Checked)
    dialog.table.setItem(1, StrategiesDialog.COL_FAV, chk1)
    dialog.table.setItem(1, StrategiesDialog.COL_RANK, QTableWidgetItem("2"))

    # Row 2: No fav, Rank 1
    chk2 = QTableWidgetItem()
    chk2.setCheckState(Qt.Unchecked)
    dialog.table.setItem(2, StrategiesDialog.COL_FAV, chk2)
    dialog.table.setItem(2, StrategiesDialog.COL_RANK, QTableWidgetItem("1"))

    # select_best should pick row 2 (rank 1)
    dialog.select_best()
    assert dialog.table.currentRow() == 2

    # select_best_favorite should pick row 1 (rank 2, because it's a fav)
    dialog.select_best_favorite()
    assert dialog.table.currentRow() == 1

def test_tree_selection():
    from strategies_dialog import StrategiesDialog
    app = QApplication.instance()
    if not app:
        app = QApplication([])

    dialog = StrategiesDialog()
    dialog.set_tree_checked(Qt.Unchecked)
    targets = dialog.get_selected_targets()
    assert len(targets) == 0

    dialog.set_tree_checked(Qt.Checked)
    targets = dialog.get_selected_targets()
    assert len(targets) == 139

def test_strategies_favorites_normalization():
    from strategies_dialog import StrategiesDialog
    from PySide6.QtCore import QSettings

    app = QApplication.instance()
    if not app:
        app = QApplication([])

    dialog = StrategiesDialog()

    # Mock strategies data
    dialog.strategies = [
        {"id": "strategy_1"},
        {"id": "strategy_2"},
        {"id": "strategy_3"}
    ]

    class MockSettings:
        def __init__(self, value_to_return):
            self._value = value_to_return
            self.saved = None

        def value(self, key, default=None):
            return self._value

        def setValue(self, key, value):
            self.saved = (key, value)

    # Test None
    dialog.settings = MockSettings(None)
    assert dialog._load_favorites() == []
    assert dialog.settings.saved == ("favorites_strategies", [])

    # Test String
    dialog.settings = MockSettings("strategy_2")
    assert dialog._load_favorites() == ["strategy_2"]

    # Test List with stale IDs and invalid types
    dialog.settings = MockSettings(["strategy_1", "stale_4", 123, "strategy_3", "strategy_1"])
    # Should only return valid, string, unique IDs and persist the cleanup.
    assert dialog._load_favorites() == ["strategy_1", "strategy_3"]
    assert dialog.settings.saved == ("favorites_strategies", ["strategy_1", "strategy_3"])
