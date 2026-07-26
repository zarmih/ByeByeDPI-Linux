import os
import shlex
import json
import subprocess
from PySide6.QtCore import QStandardPaths

class GnomeProxyAdapter:
    def __init__(self):
        self.enabled = self._check_gsettings()
        
        app_data = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        os.makedirs(app_data, exist_ok=True)
        self.journal_file = os.path.join(app_data, "gnome_proxy_journal.json")

    def _check_gsettings(self):
        try:
            # Check if gsettings is in PATH and we are in a GNOME-like environment
            # A simple way is to run gsettings --version or just which gsettings
            if not os.access("/usr/bin/gsettings", os.X_OK):
                # Try finding it in PATH
                result = subprocess.run(["which", "gsettings"], capture_output=True, text=True, timeout=2)
                if result.returncode != 0:
                    return False
                    
            # Check if we can read current proxy mode
            result = subprocess.run(["gsettings", "get", "org.gnome.system.proxy", "mode"], capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                return True
        except Exception:
            pass
        return False

    def is_available(self):
        return self.enabled

    def _get_setting(self, schema, key):
        result = subprocess.run(["gsettings", "get", schema, key], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            return result.stdout.strip()
        return None

    def _set_setting(self, schema, key, value):
        subprocess.run(["gsettings", "set", schema, key, value], timeout=2)

    def snapshot_current_state(self):
        # We save mode, and http/https host and port
        state = {
            "mode": self._get_setting("org.gnome.system.proxy", "mode"),
            "http_host": self._get_setting("org.gnome.system.proxy.http", "host"),
            "http_port": self._get_setting("org.gnome.system.proxy.http", "port"),
            "https_host": self._get_setting("org.gnome.system.proxy.https", "host"),
            "https_port": self._get_setting("org.gnome.system.proxy.https", "port"),
        }
        with open(self.journal_file, "w") as f:
            json.dump(state, f)

    def apply_proxy(self, port=1080):
        if not self.enabled:
            return False
            
        try:
            self.snapshot_current_state()
            
            # Set to manual mode
            self._set_setting("org.gnome.system.proxy", "mode", "'manual'")
            self._set_setting("org.gnome.system.proxy.http", "host", "'127.0.0.1'")
            self._set_setting("org.gnome.system.proxy.http", "port", str(port))
            self._set_setting("org.gnome.system.proxy.https", "host", "'127.0.0.1'")
            self._set_setting("org.gnome.system.proxy.https", "port", str(port))
            return True
        except Exception:
            return False

    def restore_proxy(self):
        if not self.enabled:
            return
            
        if not os.path.exists(self.journal_file):
            return
            
        try:
            with open(self.journal_file, "r") as f:
                state = json.load(f)
                
            if state.get("mode"):
                self._set_setting("org.gnome.system.proxy", "mode", state["mode"])
            if state.get("http_host"):
                self._set_setting("org.gnome.system.proxy.http", "host", state["http_host"])
            if state.get("http_port"):
                self._set_setting("org.gnome.system.proxy.http", "port", state["http_port"])
            if state.get("https_host"):
                self._set_setting("org.gnome.system.proxy.https", "host", state["https_host"])
            if state.get("https_port"):
                self._set_setting("org.gnome.system.proxy.https", "port", state["https_port"])
                
            os.remove(self.journal_file)
        except Exception:
            pass
