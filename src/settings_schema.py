import json
import logging

SCHEMA_VERSION = 1
MAX_JSON_SIZE = 100 * 1024 # 100 KB
MAX_FAVS = 200
MAX_SITES = 2000
MAX_STR_LEN = 500

def _is_safe_args(args: str) -> bool:
    lowered = args.casefold()
    sensitive = (
        "password=", "secret=", "token=", "api_key=", "apikey=",
        "cookie=", "authorization=", "/home/", "/mnt/", "c:\\",
        "~/"
    )
    return not any(marker in lowered for marker in sensitive)

def export_settings(current_settings: dict) -> str:
    """
    Exports safe settings to a JSON string.
    """
    safe_settings = {
        "schema_version": SCHEMA_VERSION,
        "profile": str(current_settings.get("profile", "Profile 1 (Default)")),
        "custom_args": str(current_settings.get("custom_args", "")),
        "favorites_strategies": list(current_settings.get("favorites_strategies", [])),
        "strategies": {
            "autosave_history": bool(current_settings.get("strategies/autosave_history", True)),
            "connect_timeout": int(current_settings.get("strategies/connect_timeout", 5)),
            "total_timeout": int(current_settings.get("strategies/total_timeout", 10)),
            "selected_target_ids": list(current_settings.get("strategies/selected_target_ids", [])),
        },
        "autostart": bool(current_settings.get("autostart", False))
    }
    if not _is_safe_args(safe_settings["custom_args"]):
        safe_settings["custom_args"] = ""
    return json.dumps(safe_settings, indent=2)

def import_settings(json_str: str) -> dict:
    """
    Validates and imports settings from a JSON string.
    Returns a dictionary of keys to update.
    """
    if len(json_str) > MAX_JSON_SIZE:
        raise ValueError("Settings file too large")

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")
        
    if not isinstance(data, dict):
        raise ValueError("Root element must be an object")
        
    if data.get("schema_version") not in (1, None):
        raise ValueError(f"Unsupported schema version: {data.get('schema_version')}")
        
    updates = {}
    
    if "profile" in data and isinstance(data["profile"], str):
        updates["profile"] = data["profile"][:MAX_STR_LEN]
    
    if "custom_args" in data and isinstance(data["custom_args"], str):
        args = data["custom_args"][:2000]
        if not _is_safe_args(args):
            raise ValueError("Unsafe arguments detected (credentials or absolute paths).")
        updates["custom_args"] = args
        
    if "favorites_strategies" in data:
        favs = data["favorites_strategies"]
        if isinstance(favs, list):
            updates["favorites_strategies"] = [str(x)[:MAX_STR_LEN] for x in favs][:MAX_FAVS]
            
    if "strategies" in data and isinstance(data["strategies"], dict):
        s = data["strategies"]
        if "autosave_history" in s:
            updates["strategies/autosave_history"] = bool(s["autosave_history"])
        if "connect_timeout" in s:
            try:
                val = int(s["connect_timeout"])
                updates["strategies/connect_timeout"] = max(1, min(60, val))
            except (ValueError, TypeError):
                pass
        if "total_timeout" in s:
            try:
                val = int(s["total_timeout"])
                updates["strategies/total_timeout"] = max(1, min(120, val))
            except (ValueError, TypeError):
                pass
        if "selected_target_ids" in s:
            tids = s["selected_target_ids"]
            if isinstance(tids, list):
                updates["strategies/selected_target_ids"] = [str(x)[:MAX_STR_LEN] for x in tids][:MAX_SITES]
                
    if "autostart" in data:
        updates["autostart"] = bool(data["autostart"])
        
    # Check for unknown top-level keys
    allowed_keys = {"schema_version", "profile", "custom_args", "favorites_strategies", "strategies", "autostart"}
    unknown_keys = set(data.keys()) - allowed_keys
    if unknown_keys:
        # We can issue a warning or ignore
        pass

    return updates

def generate_preview(current_settings: dict, updates: dict) -> dict:
    preview = {"added": [], "changed": [], "removed": [], "warnings": []}
    for k, v in updates.items():
        if k not in current_settings:
            preview["added"].append(f"{k}: {v}")
        elif str(current_settings[k]) != str(v):
            preview["changed"].append(f"{k}: {current_settings[k]} -> {v}")
    
    return preview
