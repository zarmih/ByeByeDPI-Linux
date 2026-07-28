import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

import settings_schema

def test_settings_export_import():
    current_settings = {
        "profile": "Custom",
        "custom_args": "--test-args",
        "favorites_strategies": ["s1", "s2"],
        "strategies/autosave_history": False,
        "strategies/connect_timeout": 15,
        "strategies/total_timeout": 30,
        "strategies/selected_target_ids": ["t1", "t2"],
        "autostart": True,
        "ignored_key": "should_not_export"
    }
    
    json_str = settings_schema.export_settings(current_settings)
    assert "schema_version" in json_str
    assert "--test-args" in json_str
    assert "ignored_key" not in json_str
    
    updates = settings_schema.import_settings(json_str)
    assert updates["profile"] == "Custom"
    assert updates["custom_args"] == "--test-args"
    assert updates["favorites_strategies"] == ["s1", "s2"]
    assert updates["strategies/autosave_history"] is False
    assert updates["strategies/connect_timeout"] == 15
    assert updates["strategies/total_timeout"] == 30
    assert updates["strategies/selected_target_ids"] == ["t1", "t2"]
    assert updates["autostart"] is True

def test_settings_import_validation():
    with pytest.raises(ValueError):
        settings_schema.import_settings("not json")
        
    with pytest.raises(ValueError, match="Unsupported schema version"):
        settings_schema.import_settings('{"schema_version": 999}')
        
    json_str = settings_schema.export_settings({
        "strategies/connect_timeout": 9999,
        "strategies/total_timeout": 0,
    })
    updates = settings_schema.import_settings(json_str)
    assert updates["strategies/connect_timeout"] == 60
    assert updates["strategies/total_timeout"] == 1

def test_settings_oversized_file():
    huge_json = '{"schema_version": 1, "profile": "' + 'a' * (101 * 1024) + '"}'
    with pytest.raises(ValueError, match="Settings file too large"):
        settings_schema.import_settings(huge_json)

def test_settings_secrets_rejection():
    # Exporting secrets should redact them
    s = {"custom_args": "--password=123"}
    j = settings_schema.export_settings(s)
    assert "--password" not in j
    
    # Importing secrets should fail
    bad_json = '{"schema_version": 1, "custom_args": "--token=abc"}'
    with pytest.raises(ValueError, match="Unsafe arguments detected"):
        settings_schema.import_settings(bad_json)

def test_settings_absolute_path_rejection():
    bad_json = '{"schema_version": 1, "custom_args": "--list=/home/user/list.txt"}'
    with pytest.raises(ValueError, match="Unsafe arguments detected"):
        settings_schema.import_settings(bad_json)

def test_settings_invalid_types_fallback():
    bad_types = '{"schema_version": 1, "strategies": {"connect_timeout": "abc"}}'
    updates = settings_schema.import_settings(bad_types)
    assert "strategies/connect_timeout" not in updates
