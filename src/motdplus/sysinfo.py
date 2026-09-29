"""The little facts shown in the header segments: user, host, OS, time, uptime."""

from __future__ import annotations

import getpass
import os
import platform
import re
import socket
import subprocess
import sys
import time


def user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USER") or os.environ.get("USERNAME") or "you"


def host() -> str:
    return (platform.node() or socket.gethostname() or "localhost").split(".")[0]


def os_family() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    if sys.platform.startswith("linux"):
        return "linux"
    return "os"


def os_name() -> str:
    if sys.platform == "win32":
        v = sys.getwindowsversion()
        if v.major == 10 and v.build >= 22000:
            return "Windows 11"
        return f"Windows {platform.release()}"
    if sys.platform == "darwin":
        return f"macOS {platform.mac_ver()[0]}".strip()
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            info = dict(
                line.rstrip("\n").split("=", 1) for line in f if "=" in line
            )
        name = info.get("PRETTY_NAME") or info.get("NAME")
        if name:
            return name.strip('"')
    except OSError:
        pass
    return f"{platform.system()} {platform.release()}".strip()


def uptime_seconds() -> float | None:
    try:
        if sys.platform == "win32":
            import ctypes
            tick = ctypes.windll.kernel32.GetTickCount64
            tick.restype = ctypes.c_ulonglong
            return tick() / 1000
        if os.path.exists("/proc/uptime"):
            with open("/proc/uptime") as f:
                return float(f.read().split()[0])
        out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=2).stdout
        if m := re.search(r"sec = (\d+)", out):
            return time.time() - int(m.group(1))
    except Exception:
        pass
    return None


def format_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def greeting(hour: int) -> str:
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 18:
        return "Good afternoon"
    if 18 <= hour < 24:
        return "Good evening"
    return "Up late"


_FIELD = re.compile(r"\{(\w+)\}")


def fill(template: str, values: dict[str, str]) -> str:
    """{name} substitution that leaves unknown names alone (never raises)."""
    return _FIELD.sub(lambda m: values.get(m.group(1), m.group(0)), template)


def local_time(now: float, tz: str | None) -> time.struct_time:
    """`now` in the configured IANA timezone, or the machine's own if unset/unknown."""
    if tz:
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            return datetime.fromtimestamp(now, ZoneInfo(tz)).timetuple()
        except Exception:
            pass
    return time.localtime(now)


def segments(theme_cfg: dict, *, now: float, shell: str | None = None,
             category: str | None = None) -> list[tuple[str, str]]:
    """-> [(icon key, text)] for the configured header segments, in order."""
    lt = local_time(now, theme_cfg.get("timezone"))
    try:
        stamp = time.strftime(theme_cfg.get("date_format") or "%a %d %b %H:%M", lt)
    except ValueError:
        stamp = time.strftime("%a %d %b %H:%M", lt)
    values = {
        "user": user(), "host": host(), "os": os_name(), "greeting": greeting(lt.tm_hour),
        "date": time.strftime("%Y-%m-%d", lt), "time": time.strftime("%H:%M", lt),
        "weekday": time.strftime("%A", lt),
    }
    out: list[tuple[str, str]] = []
    for name in theme_cfg.get("segments", []):
        if name == "greeting":
            text = fill(theme_cfg.get("greeting") or "{greeting}, {user}", values)
            out.append(("day" if 6 <= lt.tm_hour < 18 else "night", text))
        elif name == "user":
            out.append(("user", values["user"]))
        elif name == "host":
            out.append(("host", values["host"]))
        elif name == "os":
            out.append((os_family(), values["os"]))
        elif name == "datetime":
            out.append(("datetime", stamp))
        elif name == "uptime":
            if (up := uptime_seconds()) is not None:
                out.append(("uptime", "up " + format_duration(up)))
        elif name == "shell":
            name_ = shell or os.path.basename(os.environ.get("SHELL", "")) or ("powershell" if os.name == "nt" else "")
            if name_:
                out.append(("shell", name_))
        elif name == "category" and category:
            out.append(("category", category))
        elif name == "kernel":
            out.append(("kernel", platform.release()))
    return [(icon, text) for icon, text in out if text]


SEGMENT_CHOICES = {
    "greeting": "Greeting text",
    "user": "User name",
    "host": "Host name",
    "os": "Operating system",
    "datetime": "Date & time",
    "uptime": "Uptime",
    "shell": "Shell",
    "category": "Art category",
    "kernel": "Kernel version",
}
