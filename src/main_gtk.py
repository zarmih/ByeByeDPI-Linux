import sys
import os
import shlex
import socket
import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

from process_manager import ProcessManager

PROFILES = {
    "Profile 1 (Default)": "--disorder 1 --auto=torst --tlsrec 1+s",
    "Profile 2 (Fake)": "--fake -1 --tlsrec 1+s",
    "Profile 3 (Split)": "--split 1 --auto=torst --tlsrec 1+s",
    "Custom": ""
}

class MainWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="ByeByeDPI Linux")
        self.set_default_size(600, 400)
        self.set_border_width(10)

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.binary_path = os.path.join(base_dir, "vendor", "byedpi", "ciadpi")
        
        self.pm = ProcessManager(self.binary_path)
        self.pm.on_output = self._on_process_output
        self.pm.on_stop = self._on_process_stop

        self.init_ui()

    def init_ui(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)

        # Top panel
        top_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        vbox.pack_start(top_hbox, False, False, 0)

        top_hbox.pack_start(Gtk.Label(label="Profile:"), False, False, 0)
        
        self.profile_combo = Gtk.ComboBoxText()
        for p in PROFILES.keys():
            self.profile_combo.append_text(p)
        self.profile_combo.set_active(0)
        self.profile_combo.connect("changed", self.on_profile_changed)
        top_hbox.pack_start(self.profile_combo, False, False, 0)

        top_hbox.pack_start(Gtk.Label(label="Args:"), False, False, 0)
        self.args_entry = Gtk.Entry()
        self.args_entry.set_text(PROFILES["Profile 1 (Default)"])
        self.args_entry.set_editable(False)
        top_hbox.pack_start(self.args_entry, True, True, 0)

        # Controls panel
        controls_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        vbox.pack_start(controls_hbox, False, False, 0)

        self.start_btn = Gtk.Button(label="Start")
        self.start_btn.connect("clicked", self.start_process)
        controls_hbox.pack_start(self.start_btn, False, False, 0)

        self.stop_btn = Gtk.Button(label="Stop")
        self.stop_btn.connect("clicked", self.stop_process)
        self.stop_btn.set_sensitive(False)
        controls_hbox.pack_start(self.stop_btn, False, False, 0)

        self.status_label = Gtk.Label(label="Status: Stopped")
        controls_hbox.pack_start(self.status_label, False, False, 10)

        self.check_proxy_btn = Gtk.Button(label="Check Proxy")
        self.check_proxy_btn.connect("clicked", self.check_proxy)
        controls_hbox.pack_start(self.check_proxy_btn, False, False, 0)

        # Log area
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        vbox.pack_start(scrolled, True, True, 0)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        # set dark theme style roughly
        self.log_buffer = self.log_view.get_buffer()
        scrolled.add(self.log_view)

    def on_profile_changed(self, combo):
        profile_name = combo.get_active_text()
        args = PROFILES.get(profile_name, "")
        self.args_entry.set_text(args)
        self.args_entry.set_editable(profile_name == "Custom")

    def show_message(self, type_, title, text):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=type_,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        dialog.format_secondary_text(text)
        dialog.run()
        dialog.destroy()

    def start_process(self, btn):
        if not os.path.exists(self.binary_path):
            self.show_message(Gtk.MessageType.ERROR, "Error", f"Binary not found: {self.binary_path}\nPlease build it first.")
            return

        args = self.args_entry.get_text().strip()
        
        if self.pm.start(args):
            self.start_btn.set_sensitive(False)
            self.stop_btn.set_sensitive(True)
            self.status_label.set_text("Status: Running")
            self.profile_combo.set_sensitive(False)
            self.args_entry.set_sensitive(False)
        else:
            self.show_message(Gtk.MessageType.WARNING, "Error", "Failed to start process or open port.")

    def stop_process(self, btn):
        self.stop_btn.set_sensitive(False)
        self.pm.stop()

    def check_proxy(self, btn):
        args = self.args_entry.get_text().strip()
        try:
            args_list = shlex.split(args)
        except:
            args_list = []
        
        port = 1080
        for i, arg in enumerate(args_list):
            if arg in ('-p', '--port') and i + 1 < len(args_list):
                try:
                    port = int(args_list[i+1])
                except ValueError:
                    pass

        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                self.show_message(Gtk.MessageType.INFO, "Proxy Check", f"Proxy is reachable at 127.0.0.1:{port}")
        except OSError:
            self.show_message(Gtk.MessageType.WARNING, "Proxy Check", f"Proxy is NOT reachable at 127.0.0.1:{port}")

    def _on_process_output(self, text: str):
        GLib.idle_add(self._append_log, text)

    def _append_log(self, text):
        end_iter = self.log_buffer.get_end_iter()
        self.log_buffer.insert(end_iter, text + "\n")
        
        mark = self.log_buffer.create_mark(None, self.log_buffer.get_end_iter(), False)
        self.log_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)
        return False

    def _on_process_stop(self):
        GLib.idle_add(self._handle_stop)

    def _handle_stop(self):
        self.start_btn.set_sensitive(True)
        self.stop_btn.set_sensitive(False)
        self.status_label.set_text("Status: Stopped")
        self.profile_combo.set_sensitive(True)
        if self.profile_combo.get_active_text() == "Custom":
            self.args_entry.set_sensitive(True)
        return False

def on_destroy(win):
    win.pm.stop()
    Gtk.main_quit()

if __name__ == "__main__":
    app = MainWindow()
    app.connect("destroy", on_destroy)
    app.show_all()
    Gtk.main()
