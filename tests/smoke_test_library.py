import sys
import os
import time
from PySide6.QtWidgets import QApplication, QMessageBox
import urllib.request
import threading
import http.server

def start_mock_server(port):
    class Handler(http.server.SimpleHTTPRequestHandler):
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

    # Start a mock server for testing to avoid external dependencies
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
    dialog.show()

    # Wait a bit
    app.processEvents()

    # Select strategy 1
    dialog.table.selectRow(0)
    print("Selected strategy 1.")

    # Apply selected
    print("Applying selected strategy...")
    dialog.apply_selected()
    
    # Check if main window got it
    expected_args = dialog.table.item(0, 2).text()
    assert window.args_input.text() == expected_args

    # Test tester thread (using a simple local mock server url)
    print("Testing StrategyTesterThread...")
    dialog.url_input.setText(f"http://127.0.0.1:{mock_port}")
    strategy_id = dialog.table.item(0, 0).text()
    strategy = next((s for s in dialog.strategies if s["id"] == strategy_id), None)
    dialog.start_tester([strategy])
    
    # Wait for thread to finish (smoke test shouldn't hang)
    start = time.time()
    while dialog.tester_thread is not None and dialog.tester_thread.isRunning():
        app.processEvents()
        time.sleep(0.1)
        if time.time() - start > 10:
            print("Tester thread timed out!")
            dialog.stop_test()
            break

    print("Result in table:", dialog.table.item(0, 4).text())
    
    # Clean up
    httpd.shutdown()
    print("Library GUI smoke test passed.")

if __name__ == "__main__":
    run_smoke_test()
