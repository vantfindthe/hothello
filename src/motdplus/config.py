"""User configuration: defaults, loading (merged over defaults) and atomic saving."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from . import paths

# name -> (label, cols, rows).  cols/rows of None mean "measure the terminal";
# rows of 0 means "no height limit".
SIZE_PRESETS: dict[str, tuple[str, int | None, int | None]] = {
    "auto": ("Fit the terminal (width and height)", None, None),
    "auto-width": ("Fit the terminal width, any height (scrolls)", None, 0),
    "tiny": ("Tiny 40x12 - phones, small SSH panes", 40, 12),
    "small": ("Small 64x20", 64, 20),
    "classic": ("Classic 80x24", 80, 24),
    "wide": ("Wide 120x32", 120, 32),
    "huge": ("Huge 200x60", 200, 60),
    "custom": ("Custom width x height", None, None),
}

CYCLE_MODES = {
    "shuffle": "Shuffle - random, no repeats until every fitting piece was shown",
    "rotate": "Rotate - step through the selected categories in turn",
    "random": "Random - pure random, repeats allowed",
}

PREFER_MODES = {
    "any": "Any size that fits",
    "large": "Prefer bigger pieces (fill the screen)",
}

CHANGE_MODES = {
    "login": "Every login",
    "hourly": "Once an hour",
    "daily": "Once a day",
}

FRAMES = ["none", "single", "rounded", "double", "heavy", "ascii"]

DEFAULTS: dict = {
    "art": {
        "enabled": True,
        "categories": [],  # category ids; empty means every category
        "cycle": "shuffle",
        "change": "login",
        "prefer": "any",  # any | large - weight the pick towards pieces that fill the space
        "hide_flagged": True,  # skip pieces the site flags for nudity / explicit content
        "pages_per_refresh": 3,  # category pages fetched per background refresh
        "refresh_hours": 12,
    },
    "display": {
        "size": "auto",
        "width": 80,  # custom size, and the fallback when the terminal can't be measured
        "height": 24,
        "min_width": 10,
        "min_height": 4,
        "reserve_rows": 2,  # rows left free for the prompt
        "align": "center",
        "frame": "rounded",
        "title": True,  # the art's name (frame title / credit line)
        "credit": True,  # the art's source: artist and asciiart.website link
        "oversize": "crop",  # crop | skip - what to do when nothing cached fits
    },
    "news": {
        "enabled": True,
        "feeds": ["bbc-world", "npr", "guardian-world", "ars"],
        "custom": [],  # [{"name": ..., "url": ..., "enabled": true}]
        "count": 5,
        "per_source": 2,
        "max_age_hours": 36,
        "refresh_minutes": 30,
        "hyperlinks": "auto",  # auto | on | off
        "show_source": True,
        "show_age": True,
    },
    "system": {
        "enabled": True,
        "items": ["load", "disk", "memory", "swap", "processes", "users", "network"],
        "alerts": True,  # pending updates, restart required, new release
        "last_login": True,
        "bars": True,
    },
    "privacy": {
        # For screen recordings: hide the user and host names, IP addresses, last-login
        # address, OS/kernel versions, uptime, hardware totals and patch status.
        "enabled": False,
        "alias": "friend",  # shown instead of your user name
    },
    "animation": {
        "style": "none",  # none | lines | slide | wipe | rain | decode | nuke | random
        "speed": "normal",  # fast | normal | slow
        "target": "all",  # all | art - what the effect reveals; the rest appears at once
    },
    "theme": {
        "name": "tokyo-night",
        "header": True,
        "glyphs": "auto",  # auto | nerd | powerline | unicode | ascii
        "color": "auto",  # auto | truecolor | 256 | 16 | none
        "art_style": "theme",  # theme | plain | solid | gradient | rainbow
        "segments": ["greeting", "host", "os", "datetime", "uptime"],
        "greeting": "{greeting}, {user}",
        "date_format": "%a %d %b %H:%M",
        "timezone": "",  # e.g. "America/New_York"; empty = the machine's own
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (over or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load(path: Path | None = None) -> dict:
    """Load the config merged over DEFAULTS.  A missing or unreadable file yields
    the defaults: a broken config must never break a login shell."""
    path = path or paths.config_file()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    return _merge(DEFAULTS, data)


def save(cfg: dict, path: Path | None = None) -> None:
    path = path or paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
