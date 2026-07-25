import os
import sys
import time
import socket
import threading
import tkinter as tk

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from main_tk import MainWindow

def test_flow(app):
    try:
        print("Starting process...")
        app.start_process()
        
        # Wait for port 1080
        started = False
        for _ in range(30):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("127.0.0.1", 1080)) == 0:
                    started = True
                    break
            time.sleep(0.1)
            
        assert started, "Port 1080 did not open in time"
        print("Port 1080 is OPEN")
        
        print("Calling check_proxy()...")
        # Override messagebox to prevent blocking
        import tkinter.messagebox
        tkinter.messagebox.showinfo = lambda title, msg: print(f"MOCK info: {title} - {msg}")
        tkinter.messagebox.showwarning = lambda title, msg: print(f"MOCK warning: {title} - {msg}")
        tkinter.messagebox.showerror = lambda title, msg: print(f"MOCK error: {title} - {msg}")
        app.check_proxy()
        
        print("Stopping process...")
        app.stop_process()
        
        # Wait for port to close
        stopped = False
        for _ in range(30):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("127.0.0.1", 1080)) != 0:
                    stopped = True
                    break
            time.sleep(0.1)
            
        assert stopped, "Port 1080 did not close in time"
        print("Port 1080 is CLOSED")
        
        print("Test SUCCESS. Destroying app...")
        app.after(100, app.destroy)
        
    except Exception as e:
        print(f"Test FAILED: {e}")
        app.after(100, app.destroy)
        sys.exit(1)

def run_smoke_test():
    app = MainWindow()
    threading.Thread(target=test_flow, args=(app,), daemon=True).start()
    app.mainloop()

if __name__ == "__main__":
    run_smoke_test()
