import sys
import os
import time
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
import threading
import http.server

def start_mock_server(port):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
    httpd = http.server.HTTPServer(('127.0.0.1', port), Handler)
    thread = threading.Thread(target=httpd.serve_forever)
    thread.daemon = True
    thread.start()
    return httpd

def run_smoke_test():
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)

    mock_port = 8080
    while True:
        try:
            httpd = start_mock_server(mock_port)
            break
        except:
            mock_port += 1

    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
    from main import MainWindow
    from strategies_dialog import StrategiesDialog

    print("Starting MainWindow...")
    window = MainWindow()
    
    print("Opening StrategiesDialog...")
    dialog = StrategiesDialog(window)
    dialog.strategy_selected.connect(window.on_strategy_selected)
    
    # Inject a mock target
    dialog.target_groups = [{
        "group_id": "mock",
        "group_name": "Mock",
        "enabled_by_default": True,
        "targets": [{
            "target_id": "mock_0",
            "label": "127.0.0.1",
            "host": "127.0.0.1",
            "url": f"http://127.0.0.1:{mock_port}/"
        }]
    }]
    dialog.populate_tree()
    dialog.show()

    app.processEvents()

    # Select strategy 1
    dialog.table.selectRow(0)
    
    print("Testing StrategyTesterThread...")
    dialog.test_selected()
    
    start = time.time()
    while dialog.tester_thread is not None:
        app.processEvents()
        time.sleep(0.1)
        if time.time() - start > 10:
            print("Tester thread timed out!")
            dialog.stop_test()
            break

    # Check results in table
    passed_count = None
    for i in range(dialog.table.rowCount()):
        if dialog.table.item(i, 3).text() != "-":
            passed_count = dialog.table.item(i, 3).text()
            break
            
    print("Passed:", passed_count)
    assert passed_count == "1"
    
    from strategies_dialog import StrategyDetailsDialog
    print("Testing Details Dialog...")
    details = StrategyDetailsDialog("strategy_1", dialog.test_results.get("strategy_1", []), dialog.targets_dict, dialog)
    details.show()
    app.processEvents()
    
    httpd.shutdown()
    print("Library GUI smoke test passed.")

if __name__ == "__main__":
    run_smoke_test()
