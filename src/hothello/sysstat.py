"""System facts for the "System" section: the same things Ubuntu's login message
shows (load, disk, memory, users, addresses, pending updates, restart needed,
last login), read straight from /proc, /var and utmp so it costs milliseconds."""

from __future__ import annotations

import getpass
import ipaddress
import os
import re
import shutil
import socket
import struct
import sys
from dataclasses import dataclass, field

ITEMS = {
    "load": "Load average",
    "disk": "Disk usage of /",
    "memory": "Memory",
    "swap": "Swap",
    "processes": "Processes",
    "users": "Users logged in",
    "network": "IP addresses",
}

# Virtual interfaces that would only clutter the list (Docker, bridges, VMs, k8s).
_SKIP_IFACES = ("lo", "docker", "br-", "veth", "virbr", "vnet", "cni", "flannel", "cali", "kube", "lxc")

UTMP_RECORD = struct.Struct("<h2xi32s4s32s256shhiii4i20s")  # Linux x86_64/aarch64 `struct utmp`
USER_PROCESS = 7


@dataclass
class SysInfo:
    load: tuple[float, float, float] | None = None
    disk: tuple[int, int] | None = None  # used, total bytes
    memory: tuple[int, int] | None = None
    swap: tuple[int, int] | None = None
    processes: int | None = None
    users: int | None = None
    addresses: list[tuple[str, str]] = field(default_factory=list)  # (interface, address)
    updates: int | None = None
    security: int | None = None
    esm: int | None = None
    restart: bool = False
    restart_pkgs: list[str] = field(default_factory=list)
    release: str | None = None
    last_login: tuple[float, str] | None = None  # (unix time, from host)


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def parse_meminfo(text: str) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    kb = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        if rest.strip():
            kb[name] = int(rest.split()[0]) * 1024
    memory = swap = None
    if "MemTotal" in kb:
        avail = kb.get("MemAvailable", kb.get("MemFree", 0))
        memory = (kb["MemTotal"] - avail, kb["MemTotal"])
    if kb.get("SwapTotal"):
        swap = (kb["SwapTotal"] - kb.get("SwapFree", 0), kb["SwapTotal"])
    return memory, swap


def parse_updates(text: str) -> tuple[int | None, int | None, int | None]:
    """-> (updates, of which security, extra ESM security) from update-notifier's text."""

    def num(pattern: str) -> int | None:
        m = re.search(pattern, text)
        return int(m.group(1)) if m else None

    updates = num(r"(\d+) updates? can be applied immediately")
    if updates is None and re.search(r"\b0 updates? can be applied", text):
        updates = 0
    security = num(r"(\d+) of these updates? (?:is a|are) (?:standard )?security updates?")
    esm = num(r"(\d+) additional security updates? can be applied with ESM")
    return updates, security, esm


def read_utmp(data: bytes) -> list[tuple[str, str, str, int]]:
    """-> [(user, line, host, unix time)] for login records."""
    out = []
    size = UTMP_RECORD.size
    for off in range(0, len(data) - size + 1, size):
        rec = UTMP_RECORD.unpack_from(data, off)
        if rec[0] != USER_PROCESS:
            continue
        text = [b.split(b"\0", 1)[0].decode("utf-8", "replace") for b in (rec[2], rec[4], rec[5])]
        out.append((text[1], text[0], text[2], rec[9]))
    return out


def _utmp_tail(path: str, records: int = 400) -> bytes:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            start = max(0, end - records * UTMP_RECORD.size)
            start -= start % UTMP_RECORD.size
            f.seek(start)
            return f.read()
    except OSError:
        return b""


def last_login(user: str, current_tty: str | None) -> tuple[float, str] | None:
    """The login before this one (what sshd prints as "Last login"), from wtmp."""
    logins = [r for r in read_utmp(_utmp_tail("/var/log/wtmp")) if r[0] == user and not r[2].startswith("tmux(")]
    logins.sort(key=lambda r: r[3], reverse=True)
    if logins and current_tty and logins[0][1] == current_tty:
        logins = logins[1:]  # that one is us
    if not logins:
        return None
    _, line, host, when = logins[0]
    return float(when), host or line


def _ipv4(iface: str) -> str | None:
    try:
        import fcntl

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            packed = fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", iface[:15].encode()))  # SIOCGIFADDR
        return socket.inet_ntoa(packed[20:24])
    except OSError:
        return None


def addresses() -> list[tuple[str, str]]:
    try:
        ifaces = sorted(n for n in os.listdir("/sys/class/net") if not n.startswith(_SKIP_IFACES))
    except OSError:
        return []
    out = [(i, a) for i in ifaces if (a := _ipv4(i))]
    for line in (_read("/proc/net/if_inet6") or "").splitlines():
        parts = line.split()
        if len(parts) == 6 and parts[3] == "00" and parts[5] in ifaces:  # scope 00 = global
            out.append((parts[5], str(ipaddress.IPv6Address(bytes.fromhex(parts[0])))))
    order = {name: i for i, name in enumerate(ifaces)}
    return sorted(out, key=lambda p: order.get(p[0], 99))


def gather(system_cfg: dict) -> SysInfo:
    info = SysInfo()
    items = set(system_cfg.get("items", ITEMS))
    try:
        if "load" in items and hasattr(os, "getloadavg"):
            info.load = os.getloadavg()
    except OSError:
        pass
    if "disk" in items:
        try:
            du = shutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\" if os.name == "nt" else "/")
            info.disk = (du.used, du.total)
        except OSError:
            pass
    if items & {"memory", "swap"}:
        if (text := _read("/proc/meminfo")) is not None:
            info.memory, info.swap = parse_meminfo(text)
        elif os.name == "nt":
            info.memory = _windows_memory()
    if "processes" in items and os.path.isdir("/proc/1"):
        info.processes = sum(1 for n in os.listdir("/proc") if n.isdigit())
    if "users" in items and os.path.exists("/var/run/utmp"):
        info.users = len({r[0] for r in read_utmp(_utmp_tail("/var/run/utmp"))})
    if "network" in items and sys.platform.startswith("linux"):
        info.addresses = addresses()
    if system_cfg.get("alerts", True):
        if (text := _read("/var/lib/update-notifier/updates-available")) is not None:
            info.updates, info.security, info.esm = parse_updates(text)
        info.restart = os.path.exists("/var/run/reboot-required")
        info.restart_pkgs = (_read("/var/run/reboot-required.pkgs") or "").split()
        release = (_read("/var/lib/ubuntu-release-upgrader/release-upgrade-available") or "").strip()
        info.release = release.splitlines()[0].strip() if release else None
    if system_cfg.get("last_login", True) and os.path.exists("/var/log/wtmp"):
        try:
            tty = os.ttyname(0).removeprefix("/dev/")
        except OSError:
            tty = None
        try:
            info.last_login = last_login(getpass.getuser(), tty)
        except Exception:
            pass
    return info


def _windows_memory() -> tuple[int, int] | None:
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return stat.ullTotalPhys - stat.ullAvailPhys, stat.ullTotalPhys
    except Exception:
        return None


def human(n: float) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit in ("B", "K") or n >= 100 else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.0f}P"
