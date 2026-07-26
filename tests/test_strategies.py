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
    
    app = QApplication.instance()
    if not app:
        app = QApplication([])
        
    dialog = StrategiesDialog()
    
    # Mock data
    dialog.table.setRowCount(3)
    
    from PySide6.QtWidgets import QTableWidgetItem
    dialog.table.setItem(0, 1, QTableWidgetItem("strategy_1"))
    
    # Let's mock a fast strategy (row 2), a slow strategy (row 0), and a failed strategy (row 1)
    # The rank string is in column 0.
    dialog.table.setItem(0, 0, QTableWidgetItem("2")) # Rank 2
    dialog.table.setItem(1, 0, QTableWidgetItem(""))  # No rank (failed)
    dialog.table.setItem(2, 0, QTableWidgetItem("1")) # Rank 1
    
    dialog.select_best()
    assert dialog.table.item(dialog.table.currentRow(), 0).text() == "1"

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
