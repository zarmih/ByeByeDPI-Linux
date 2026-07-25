import os
import sys
import time
import socket
import threading

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from main_gtk import MainWindow

def test_flow(app):
    try:
        print("Starting process...")
        GLib.idle_add(app.start_process, None)
        
        # Wait for port 1080
        started = False
        for _ in range(50):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("127.0.0.1", 1080)) == 0:
                    started = True
                    break
            time.sleep(0.1)
            
        if not started:
            print("Port 1080 did not open in time")
            sys.exit(1)
        print("Port 1080 is OPEN")
        
        print("Calling check_proxy()...")
        # Override show_message to prevent blocking
        app.show_message = lambda type_, title, text: print(f"MOCK Dialog: {title} - {text}")
        GLib.idle_add(app.check_proxy, None)
        
        time.sleep(1) # let the check proxy execute
        
        print("Stopping process...")
        GLib.idle_add(app.stop_process, None)
        
        # Wait for port to close
        stopped = False
        for _ in range(50):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("127.0.0.1", 1080)) != 0:
                    stopped = True
                    break
            time.sleep(0.1)
            
        if not stopped:
            print("Port 1080 did not close in time")
            sys.exit(1)
        print("Port 1080 is CLOSED")
        
        print("Test SUCCESS. Destroying app...")
        GLib.idle_add(app.destroy)
        GLib.idle_add(Gtk.main_quit)
        
    except Exception as e:
        print(f"Test FAILED: {e}")
        GLib.idle_add(app.destroy)
        GLib.idle_add(Gtk.main_quit)
        sys.exit(1)

def run_smoke_test():
    app = MainWindow()
    app.connect("destroy", Gtk.main_quit)
    threading.Thread(target=test_flow, args=(app,), daemon=True).start()
    Gtk.main()

if __name__ == "__main__":
    run_smoke_test()
