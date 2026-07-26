import os
import tempfile
import json
import csv
import sys
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QStandardPaths

import result_bundle
from history_dialog import HistoryDialog

app = QApplication.instance() or QApplication(sys.argv)

@pytest.fixture
def temp_history_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d

def test_bundle_creation_and_recompute():
    targets = [{"target_id": "t1", "host": "example.com", "group_name": "TestGroup"}]
    strategies = [{"id": "s1", "args": "--fake"}]
    results = {
        "s1": [
            {"target_id": "t1", "status": "Success", "duration": 0.5, "http_code": 200, "error_msg": ""}
        ]
    }

    bundle = result_bundle.create_bundle(
        strategies, targets, results,
        0, 10, "completed", 1, 1, 1, 1,
        {"repo": "test", "commit": "test"},
        {"timeout": 5, "policy": "test"}
    )

    assert bundle["schema_version"] == 2
    assert bundle["best_strategy_id"] == "s1"
    assert bundle["run_metadata"]["state"] == "completed"

    bundle["aggregates"]["strategies"]["s1"]["passed"] = 999

    b2, warnings = result_bundle.validate_and_migrate(bundle)
    assert len(warnings) > 0
    assert "Aggregates mismatch found. Recomputed." in warnings
    assert b2["aggregates"]["strategies"]["s1"]["passed"] == 1

def test_migration_v1():
    v1_data = {
        "metadata": {
            "strategies": ["s1"],
            "policy": "test"
        },
        "results": {
            "s1": [
                {"target_id": "t1", "status": "Timeout", "duration": 5.0, "http_code": 0, "error_msg": ""}
            ]
        }
    }
    b2, warnings = result_bundle.validate_and_migrate(v1_data)
    assert b2["schema_version"] == 2
    assert b2["run_metadata"]["state"] == "imported_v1"
    assert b2["aggregates"]["strategies"]["s1"]["timeouts"] == 1

def test_csv_export():
    targets = [{"target_id": "t1", "host": "ex,ample.com", "group_name": "Test Group"}]
    strategies = [{"id": "s1", "args": "--fake"}]
    results = {
        "s1": [{"target_id": "t1", "status": "Error", "duration": 0.0, "http_code": 0, "error_msg": "test,error\nnew line"}]
    }
    bundle = result_bundle.create_bundle(
        strategies, targets, results,
        0, 1, "completed", 1, 1, 1, 1, {}, {}
    )

    with tempfile.TemporaryDirectory() as d:
        flat_path = os.path.join(d, "flat.csv")
        result_bundle.export_csv_flat(bundle, flat_path)
        with open(flat_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            rows = list(reader)
            assert len(rows) == 2
            assert rows[1][3] == "ex,ample.com"

        sum_path = os.path.join(d, "sum.csv")
        result_bundle.export_csv_summary(bundle, sum_path)
        with open(sum_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            rows = list(reader)
            assert len(rows) == 2

def test_history_limit_and_atomic(temp_history_dir):
    bundle = {"schema_version": 2, "run_metadata": {"state": "completed"}, "results": {}, "aggregates": {"strategies": {}}}
    for i in range(25):
        result_bundle.save_to_history(bundle, test_path=temp_history_dir)
        import time
        time.sleep(0.01)

    records = result_bundle.list_history(temp_history_dir)
    assert len(records) == 20

    result_bundle.delete_history_record(records[0]["filepath"], test_path=temp_history_dir)
    assert len(result_bundle.list_history(temp_history_dir)) == 19

    result_bundle.clear_history(temp_history_dir)
    assert len(result_bundle.list_history(temp_history_dir)) == 0

def test_comparison():
    b1 = {"aggregates": {"strategies": {"s1": {"passed": 5, "success_rate": 50, "median_time": 1.0, "timeouts": 0, "errors": 0}}}, "ranking_order": ["s1"]}
    b2 = {"aggregates": {"strategies": {"s1": {"passed": 3, "success_rate": 30, "median_time": 1.5, "timeouts": 0, "errors": 0}}}, "ranking_order": ["s1"]}

    comp = result_bundle.compare_bundles(b1, b2)
    assert len(comp) == 1
    assert comp[0]["d_passed"] == 2
    assert comp[0]["d_pct"] == 20.0
    assert comp[0]["d_med"] == -0.5
    assert comp[0]["d_rank"] == 0

def test_history_dialog_smoke(temp_history_dir, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    class FakeMessageBox:
        Yes = 1
        No = 2
        @staticmethod
        def question(*args):
            return 1

    monkeypatch.setattr("history_dialog.QMessageBox", FakeMessageBox)

    bundle = {"schema_version": 2, "run_metadata": {"state": "completed"}, "results": {}, "aggregates": {"strategies": {}}}
    result_bundle.save_to_history(bundle, test_path=temp_history_dir)

    dlg = HistoryDialog(test_path=temp_history_dir)
    assert dlg.table.rowCount() == 1

    dlg.table.selectRow(0)
    dlg.on_open()
    assert dlg.opened_filepath is not None

    dlg.on_clear()
    assert dlg.table.rowCount() == 0

def test_oversized_file(temp_history_dir):
    filepath = os.path.join(temp_history_dir, "huge.json")
    with open(filepath, 'w') as f:
        f.seek(51 * 1024 * 1024)
        f.write('0')

    with pytest.raises(ValueError, match="too large"):
        result_bundle.load_bundle(filepath)

def test_remove_secrets():
    data = {
        "API_KEY": "supersecret",
        "nested": {
            "my_cookie": "yummy",
            "normal_value": "hello",
            "path": "/mnt/" + "SDD/file.txt",
            "path2": "file:///etc/passwd"
        },
        "url": "http://example.com/api?token=abc"
    }
    cleaned = result_bundle._remove_secrets(data)
    assert cleaned["API_KEY"] == "***REDACTED***"
    assert cleaned["nested"]["my_cookie"] == "***REDACTED***"
    assert cleaned["nested"]["normal_value"] == "hello"
    assert cleaned["nested"]["path"] == "***REDACTED_PATH***"
    assert cleaned["nested"]["path2"] == "***REDACTED_PATH***"
    assert "abc" not in cleaned["url"]
    assert "REDACTED" in cleaned["url"]
    credential_url = result_bundle._remove_secrets("https://user:pass@example.com/path?api_key=123&safe=yes")
    assert "user:pass" not in credential_url
    assert "123" not in credential_url
    assert "safe=yes" in credential_url

def test_path_traversal(temp_history_dir):
    with pytest.raises(ValueError, match="Path traversal"):
        result_bundle.delete_history_record(os.path.join(temp_history_dir, "..", "fake.json"), test_path=temp_history_dir)

def test_invalid_url_and_state():
    bundle = {
        "schema_version": 2,
        "run_metadata": {"state": "weird"},
        "snapshots": {"targets": [{"url": "ftp://bad"}]}
    }
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "test.json")
        with open(p, "w") as f:
            json.dump(bundle, f)
        with pytest.raises(ValueError, match="Invalid state"):
            result_bundle.load_bundle(p)

        bundle["run_metadata"]["state"] = "completed"
        with open(p, "w") as f:
            json.dump(bundle, f)
        with pytest.raises(ValueError, match="Invalid URL"):
            result_bundle.load_bundle(p)

def test_forged_ranking():
    bundle = {
        "schema_version": 2,
        "run_metadata": {"state": "completed"},
        "results": {
            "s1": [{"status": "Success", "duration": 1.0}],
            "s2": [{"status": "Success", "duration": 0.5}]
        },
        "ranking_order": ["s1", "s2"],
        "best_strategy_id": "s1"
    }
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "test.json")
        with open(p, "w") as f:
            json.dump(bundle, f)
        b2, warnings = result_bundle.load_bundle(p)

    assert b2["ranking_order"] == ["s2", "s1"]
    assert b2["best_strategy_id"] == "s2"
    assert any("Ranking mismatch found" in w for w in warnings)

def test_history_dir_creation():
    d = result_bundle.get_history_dir()
    assert "ByeByeDPI-Linux" in d
    assert "history" in d
    assert os.path.exists(d)
