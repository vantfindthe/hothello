"""Terminal capability detection: size, colour depth, hyperlinks, Windows VT mode."""

from __future__ import annotations

import os
import sys

_vt_ok: bool | None = None


def enable_vt() -> bool:
    """Turn on ANSI escape processing in a Windows console (a no-op elsewhere)."""
    global _vt_ok
    if _vt_ok is not None:
        return _vt_ok
    if os.name != "nt":
        _vt_ok = True
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            _vt_ok = True  # not a console (pipe or file): whoever reads it decides
        elif mode.value & 0x0004:
            _vt_ok = True
        else:
            _vt_ok = bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        _vt_ok = False
    return _vt_ok


def measure() -> tuple[int, int] | None:
    for stream in (sys.__stdout__, sys.__stderr__, sys.__stdin__):
        try:
            size = os.get_terminal_size(stream.fileno())  # type: ignore[union-attr]
            if size.columns > 0 and size.lines > 0:
                return size.columns, size.lines
        except (AttributeError, OSError, ValueError):
            continue
    try:
        cols, rows = int(os.environ["COLUMNS"]), int(os.environ["LINES"])
        if cols > 0 and rows > 0:
            return cols, rows
    except (KeyError, ValueError):
        pass
    return None


_TRUECOLOR_PROGRAMS = {"iTerm.app", "WezTerm", "vscode", "ghostty", "Hyper", "Tabby", "rio"}


def detect_color() -> str:
    env = os.environ
    if env.get("NO_COLOR"):
        return "none"
    term = env.get("TERM", "")
    if term == "dumb":
        return "none"
    if env.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return "truecolor"
    if (env.get("WT_SESSION") or env.get("TERM_PROGRAM") in _TRUECOLOR_PROGRAMS
            or env.get("KITTY_WINDOW_ID") or "kitty" in term or "alacritty" in term):
        return "truecolor"
    if os.name == "nt":
        return "truecolor" if enable_vt() else "none"
    if "256" in term:
        return "256"
    return "16"


def detect_hyperlinks(setting: str) -> bool:
    if setting == "on":
        return True
    if setting == "off":
        return False
    env = os.environ
    if env.get("WT_SESSION") or env.get("KITTY_WINDOW_ID") or env.get("TERM_PROGRAM") in {
        "iTerm.app", "WezTerm", "vscode", "ghostty", "Tabby", "rio"
    }:
        return True
    try:
        return int(env.get("VTE_VERSION", "0")) >= 5000
    except ValueError:
        return False
