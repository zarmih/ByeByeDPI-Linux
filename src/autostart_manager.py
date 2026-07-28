import os
import sys

def get_autostart_path():
    config_home = os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
    return os.path.join(config_home, 'autostart', 'byebyedpi-linux.desktop')

def _is_safe_launcher(path):
    if not os.path.isabs(path) or not os.path.exists(path):
        return False
    if "byebyedpi-linux" not in path.lower():
        return False
    return True

def set_autostart(enabled: bool, launcher_path: str = None) -> tuple[bool, str]:
    path = get_autostart_path()
    
    if not enabled:
        if os.path.lexists(path):
            try:
                os.unlink(path)
                return True, "Autostart disabled."
            except Exception as e:
                return False, f"Failed to remove autostart file: {e}"
        return True, "Already disabled."

    if not launcher_path:
        candidates = [
            os.path.expanduser("~/.local/bin/byebyedpi-linux"),
            "/usr/local/bin/byebyedpi-linux",
            "/usr/bin/byebyedpi-linux"
        ]
        for c in candidates:
            if os.path.exists(c):
                launcher_path = c
                break
                
        if not launcher_path:
            return False, "Could not find a safely installed launcher (e.g. ~/.local/bin/byebyedpi-linux). In dev mode autostart is disabled."

    if not _is_safe_launcher(launcher_path):
        return False, "Launcher path is unsafe or invalid for autostart."

    desktop_content = f"""[Desktop Entry]
Type=Application
Name=ByeByeDPI
Exec={launcher_path}
Icon=byebyedpi
Terminal=false
Categories=Network;Utility;
X-GNOME-Autostart-enabled=true
"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        
        # If the target exists and is a symlink, remove it first to avoid following it
        if os.path.lexists(path) and os.path.islink(path):
            os.unlink(path)
            
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(desktop_content)
            f.flush()
            os.fsync(f.fileno())
            
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, path)
        return True, "Autostart enabled."
    except Exception as e:
        return False, f"Failed to create autostart file: {e}"

def is_autostart_enabled() -> bool:
    path = get_autostart_path()
    return os.path.exists(path) and not os.path.islink(path)
