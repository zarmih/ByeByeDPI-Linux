import sys
import os
import time
import shutil
import tempfile
import threading
import http.server

_SMOKE_ROOT = tempfile.mkdtemp(prefix="byebyedpi-library-smoke-")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["XDG_CONFIG_HOME"] = os.path.join(_SMOKE_ROOT, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_SMOKE_ROOT, "data")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

def start_mock_server(port):
    class Handler(http.server.SimpleHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

        def do_GET(self):
            body = b"OK"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            self.close_connection = True

    class ReuseHTTPServer(http.server.HTTPServer):
        allow_reuse_address = True

    httpd = ReuseHTTPServer(('127.0.0.1', port), Handler)
    thread = threading.Thread(target=httpd.serve_forever)
    thread.daemon = True
    thread.start()
    return httpd, thread

def run_smoke_test():
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)

    mock_port = 8080
    while True:
        try:
            httpd, server_thread = start_mock_server(mock_port)
            break
        except Exception:
            mock_port += 1

    try:
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
        dialog.set_tree_checked(Qt.Checked)
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
                break

        # Check results in table
        passed_count = None
        for i in range(dialog.table.rowCount()):
            if dialog.table.item(i, StrategiesDialog.COL_PASSED).text() != "-":
                passed_count = dialog.table.item(i, StrategiesDialog.COL_PASSED).text()
                break

        print("Passed:", passed_count)
        assert passed_count == "1"

        from strategies_dialog import StrategyDetailsDialog
        print("Testing Details Dialog...")
        details = StrategyDetailsDialog("strategy_1", dialog.test_results.get("strategy_1", []), dialog.targets_dict, dialog)
        details.show()
        app.processEvents()
        print("Library GUI smoke test passed.")

    finally:
        print("Cleaning up...")
        if 'dialog' in locals() and dialog:
            dialog.stop_test()
            if dialog.tester_thread:
                dialog.tester_thread.wait(2000)
            dialog.close()
        if 'details' in locals() and details:
            details.close()
        if 'window' in locals() and window:
            window.close()

        httpd.shutdown()
        httpd.server_close()
        server_thread.join(timeout=2.0)
        app.processEvents()
        shutil.rmtree(_SMOKE_ROOT, ignore_errors=True)

if __name__ == "__main__":
    run_smoke_test()
