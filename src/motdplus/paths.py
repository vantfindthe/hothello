"""Filesystem locations.

Setting MOTDPLUS_HOME puts config and cache in one directory, which is what
tests and the system-wide update-motd.d install use.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP = "motdplus"


def _override() -> Path | None:
    value = os.environ.get("MOTDPLUS_HOME")
    return Path(value).expanduser() if value else None


def config_dir() -> Path:
    if (override := _override()) is not None:
        return override
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / APP


def cache_dir() -> Path:
    if (override := _override()) is not None:
        return override
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / APP


def config_file() -> Path:
    return config_dir() / "config.json"


def themes_dir() -> Path:
    return config_dir() / "themes"


def db_file() -> Path:
    return cache_dir() / "motdplus.db"


def lock_file() -> Path:
    return cache_dir() / "refresh.lock"


def log_file() -> Path:
    return cache_dir() / "refresh.log"
