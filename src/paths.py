from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths


APP_DATA_DIR_NAME = "ByeByeDPI-Linux"
ORGANIZATION_NAME = "ByeByeDPI"
APPLICATION_NAME = "ByeByeDPI-Linux"


def _writable_location(location) -> str:
    return QStandardPaths.writableLocation(location)


def user_data_dir(*, create: bool = True) -> Path:
    base = Path(_writable_location(QStandardPaths.GenericDataLocation))
    path = base / APP_DATA_DIR_NAME
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def user_config_dir(*, create: bool = True) -> Path:
    base = Path(_writable_location(QStandardPaths.GenericConfigLocation))
    path = base / APP_DATA_DIR_NAME
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def legacy_data_dirs() -> tuple[Path, ...]:
    """Known paths produced by older AppDataLocation-based releases."""
    base = Path(_writable_location(QStandardPaths.GenericDataLocation))
    candidates = (
        base / ORGANIZATION_NAME / APPLICATION_NAME,
        base / ORGANIZATION_NAME / APPLICATION_NAME / APP_DATA_DIR_NAME,
        base / APP_DATA_DIR_NAME / APP_DATA_DIR_NAME,
    )
    current = user_data_dir(create=False)
    unique = []
    for candidate in candidates:
        if candidate != current and candidate not in unique:
            unique.append(candidate)
    return tuple(unique)


def data_search_dirs() -> tuple[Path, ...]:
    return (user_data_dir(create=False),) + legacy_data_dirs()
