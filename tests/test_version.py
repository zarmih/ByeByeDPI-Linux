from __future__ import annotations

import re
from pathlib import Path

from version import __version__


def test_runtime_version_matches_project_metadata():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert match
    assert __version__ == match.group(1)


def test_runtime_version_is_semantic_triplet():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)
