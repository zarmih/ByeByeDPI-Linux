import sys
import os

# Add src to path so we can import from it
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from main import PROFILES

def test_profiles_exist():
    assert "Profile 1 (Default)" in PROFILES
    assert "Custom" in PROFILES
    assert PROFILES["Custom"] == ""
    assert "--disorder" in PROFILES["Profile 1 (Default)"]
