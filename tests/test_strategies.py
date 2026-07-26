import json
import os
import shlex
import pytest
from PySide6.QtWidgets import QApplication

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
        
def test_strategy_tester_logic():
    # Smoke test the tester logic
    from strategy_tester import StrategyTesterThread
    strategies = [
        {"id": "strategy_1", "args": "--fake -1", "supported": True}
    ]
    
    tester = StrategyTesterThread(strategies, "http://127.0.0.1:0")
    
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
    
    # Format: "Success (1.23s) 200"
    from PySide6.QtWidgets import QTableWidgetItem
    dialog.table.setItem(0, 4, QTableWidgetItem("Success (2.50s) 200"))
    dialog.table.setItem(1, 4, QTableWidgetItem("Timeout (10.00s)"))
    dialog.table.setItem(2, 4, QTableWidgetItem("Success (1.10s) 200"))
    
    dialog.select_best()
    assert dialog.table.currentRow() == 2

