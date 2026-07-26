import sys
import os
import tkinter as tk
from tkinter import ttk, messagebox
import shlex
import socket
import queue

from process_manager import ProcessManager

PROFILES = {
    "Profile 1 (Default)": "--disorder 1 --auto=torst --tlsrec 1+s",
    "Profile 2 (Fake)": "--fake -1 --tlsrec 1+s",
    "Profile 3 (Split)": "--split 1 --auto=torst --tlsrec 1+s",
    "Custom": ""
}

class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ByeByeDPI Linux")
        self.geometry("600x400")

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.binary_path = os.path.join(base_dir, "vendor", "byedpi", "ciadpi")
        
        self.pm = ProcessManager(self.binary_path)
        self.pm.on_output = self._on_process_output
        self.pm.on_stop = self._on_process_stop

        self.queue = queue.Queue()
        self.init_ui()
        self.process_queue()

    def init_ui(self):
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Top panel
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.X, pady=5)

        ttk.Label(top_frame, text="Profile:").pack(side=tk.LEFT, padx=5)
        self.profile_var = tk.StringVar(value="Profile 1 (Default)")
        self.profile_combo = ttk.Combobox(top_frame, textvariable=self.profile_var, values=list(PROFILES.keys()), state="readonly")
        self.profile_combo.pack(side=tk.LEFT, padx=5)
        self.profile_combo.bind("<<ComboboxSelected>>", self.on_profile_changed)

        ttk.Label(top_frame, text="Args:").pack(side=tk.LEFT, padx=5)
        self.args_var = tk.StringVar(value=PROFILES["Profile 1 (Default)"])
        self.args_input = ttk.Entry(top_frame, textvariable=self.args_var, state="readonly")
        self.args_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Controls panel
        controls_frame = ttk.Frame(main_frame)
        controls_frame.pack(fill=tk.X, pady=5)

        self.start_btn = ttk.Button(controls_frame, text="Start", command=self.start_process)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(controls_frame, text="Stop", command=self.stop_process, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.status_var = tk.StringVar(value="Status: Stopped")
        self.status_label = ttk.Label(controls_frame, textvariable=self.status_var, foreground="gray")
        self.status_label.pack(side=tk.LEFT, padx=15)

        self.check_proxy_btn = ttk.Button(controls_frame, text="Check Proxy", command=self.check_proxy)
        self.check_proxy_btn.pack(side=tk.LEFT, padx=5)

        # Log area
        self.log_area = tk.Text(main_frame, state=tk.DISABLED, bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 10))
        self.log_area.pack(fill=tk.BOTH, expand=True, pady=5)

    def on_profile_changed(self, event=None):
        profile_name = self.profile_var.get()
        args = PROFILES.get(profile_name, "")
        self.args_var.set(args)
        if profile_name == "Custom":
            self.args_input.config(state=tk.NORMAL)
        else:
            self.args_input.config(state="readonly")

    def start_process(self):
        if not os.path.exists(self.binary_path):
            messagebox.showerror("Error", f"Binary not found: {self.binary_path}\nPlease build it first.")
            return

        args = self.args_var.get().strip()
        
        if self.pm.start(args):
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.status_var.set("Status: Running")
            self.status_label.config(foreground="green")
            self.profile_combo.config(state=tk.DISABLED)
            self.args_input.config(state=tk.DISABLED)
        else:
            messagebox.showwarning("Error", "Failed to start process or open port.")

    def stop_process(self):
        self.stop_btn.config(state=tk.DISABLED)
        self.pm.stop()

    def check_proxy(self):
        args = self.args_var.get().strip()
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
                messagebox.showinfo("Proxy Check", f"Proxy is reachable at 127.0.0.1:{port}")
        except OSError:
            messagebox.showwarning("Proxy Check", f"Proxy is NOT reachable at 127.0.0.1:{port}")

    def _on_process_output(self, text: str):
        self.queue.put(("log", text))

    def _on_process_stop(self):
        self.queue.put(("stopped", None))

    def process_queue(self):
        try:
            while True:
                msg_type, data = self.queue.get_nowait()
                if msg_type == "log":
                    self.log_area.config(state=tk.NORMAL)
                    self.log_area.insert(tk.END, data + "\n")
                    self.log_area.see(tk.END)
                    self.log_area.config(state=tk.DISABLED)
                elif msg_type == "stopped":
                    self.start_btn.config(state=tk.NORMAL)
                    self.stop_btn.config(state=tk.DISABLED)
                    self.status_var.set("Status: Stopped")
                    self.status_label.config(foreground="gray")
                    self.profile_combo.config(state="readonly")
                    if self.profile_var.get() == "Custom":
                        self.args_input.config(state=tk.NORMAL)
        except queue.Empty:
            pass
        self.after(100, self.process_queue)

    def destroy(self):
        self.pm.stop()
        super().destroy()

if __name__ == "__main__":
    app = MainWindow()
    app.mainloop()
