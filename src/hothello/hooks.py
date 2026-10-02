"""Installing / removing the login hook that runs `hothello show`.

Hooks live between marker lines, so installing twice is harmless and
uninstalling removes exactly what was added.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from . import paths

BEGIN = "# >>> hothello >>>"
END = "# <<< hothello <<<"
UPDATE_MOTD = Path("/etc/update-motd.d/60-hothello")
SYSTEM_HOME = "/var/lib/hothello"


def documents_dir() -> Path:
    """The real Documents folder (it is often redirected into OneDrive)."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            folder_id = GUID(0xFDD39AD0, 0x238F, 0x46AF,
                             (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(out)) == 0:
                path = out.value
                ctypes.windll.ole32.CoTaskMemFree(out)
                if path:
                    return Path(path)
        except Exception:
            pass
    return Path.home() / "Documents"


@dataclass
class Target:
    key: str
    label: str
    path: Path
    whole_file: bool = False  # the hook owns the entire file
    system: bool = False  # needs root


def targets() -> dict[str, Target]:
    home = Path.home()
    out: dict[str, Target] = {}
    if os.name == "nt":
        docs = documents_dir()
        out["powershell"] = Target("powershell", "Windows PowerShell 5.1", docs / "WindowsPowerShell" / "profile.ps1")
        out["pwsh"] = Target("pwsh", "PowerShell 7+", docs / "PowerShell" / "profile.ps1")
    else:
        out["bash"] = Target("bash", "bash (~/.bashrc)", home / ".bashrc")
        out["zsh"] = Target("zsh", "zsh (~/.zshrc)", home / ".zshrc")
        out["fish"] = Target("fish", "fish (conf.d)", home / ".config" / "fish" / "conf.d" / "hothello.fish", whole_file=True)
        out["pwsh"] = Target("pwsh", "PowerShell 7+", home / ".config" / "powershell" / "profile.ps1")
        if sys.platform.startswith("linux"):
            out["update-motd"] = Target("update-motd", "System MOTD (/etc/update-motd.d, all users, needs root)",
                                        UPDATE_MOTD, whole_file=True, system=True)
    return out


def relevant_targets() -> dict[str, Target]:
    """Targets worth offering on this machine: shells that exist, or hooks already installed."""
    out = {}
    for key, target in targets().items():
        exe = {"zsh": "zsh", "fish": "fish", "pwsh": "pwsh"}.get(key)
        if exe is None or shutil.which(exe) or is_installed(target):
            out[key] = target
    return out


def default_targets() -> list[str]:
    if os.name == "nt":
        return ["powershell", "pwsh"] if shutil.which("pwsh") else ["powershell"]
    shell = Path(os.environ.get("SHELL", "bash")).name
    return [shell] if shell in ("bash", "zsh", "fish") else ["bash"]


def _q_ps(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _q_sh(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _pkg_root() -> str:
    return str(Path(__file__).resolve().parent.parent)


def snippet(key: str, python: str) -> str:
    root = _pkg_root()
    if key in ("powershell", "pwsh"):
        # Only interactive sessions: skip -NonInteractive, and -Command/-File runs
        # unless -NoExit keeps them open (as VS Code's terminal does).
        return "\n".join([
            BEGIN + "  (managed by `hothello install`; remove with `hothello uninstall`)",
            "function hothello {",
            "    $hothelloSaved = $env:PYTHONPATH",
            f"    $env:PYTHONPATH = {_q_ps(root)}",
            f"    try {{ & {_q_ps(python)} -m hothello @args }} finally {{ $env:PYTHONPATH = $hothelloSaved }}",
            "}",
            "$hothelloArgs = [Environment]::GetCommandLineArgs()",
            "if (-not $env:HOTHELLO_SHOWN -and [Environment]::UserInteractive -and",
            "    -not ($hothelloArgs -match '^[-/]noni') -and",
            "    (($hothelloArgs -match '^[-/]noe') -or",
            "     -not ($hothelloArgs -match '^[-/](c|command|f|file|e|ec|encodedcommand|cwa|commandwithargs)$'))) {",
            "    $env:HOTHELLO_SHOWN = '1'",
            "    $hothelloSaved = $env:PYTHONPATH",
            f"    $env:PYTHONPATH = {_q_ps(root)}",
            f"    try {{ & {_q_ps(python)} -m hothello show --shell {key} }} catch {{ }}",
            "    finally { $env:PYTHONPATH = $hothelloSaved }",
            "    Remove-Variable hothelloSaved",
            "}",
            "Remove-Variable hothelloArgs",
            END,
        ])
    if key == "bash":
        cond = '[[ $- == *i* && -z "$HOTHELLO_SHOWN" ]]'
    elif key == "zsh":
        cond = '[[ -o interactive && -z "$HOTHELLO_SHOWN" ]]'
    elif key == "fish":
        return "\n".join([
            BEGIN,
            "if status is-interactive; and not set -q HOTHELLO_SHOWN",
            "    set -gx HOTHELLO_SHOWN 1",
            "    set -g fish_greeting ''  # hothello replaces the default greeting",
            f"    env PYTHONPATH={_q_sh(root)} {_q_sh(python)} -m hothello show --shell fish 2>/dev/null",
            "end",
            END,
        ])
    elif key == "update-motd":
        return "\n".join([
            "#!/bin/sh",
            BEGIN,
            "# Runs at every login via pam_motd.  Config and cache live in " + SYSTEM_HOME + ";",
            "# there is no terminal to measure here, so set a size in the config (Display tab).",
            f"HOTHELLO_HOME={SYSTEM_HOME} PYTHONPATH={_q_sh(root)} exec {_q_sh(python)} -m hothello show --shell login 2>/dev/null",
            END,
        ])
    else:
        raise ValueError(f"unknown target {key!r}")
    return "\n".join([
        BEGIN,
        f"if {cond}; then",
        "  export HOTHELLO_SHOWN=1",
        f"  PYTHONPATH={_q_sh(root)} {_q_sh(python)} -m hothello show --shell {key} 2>/dev/null",
        "fi",
        END,
    ])


def _default_newline(path: Path) -> str:
    return "\r\n" if path.suffix == ".ps1" and os.name == "nt" else "\n"


def _read(path: Path) -> tuple[str, str, str]:
    """-> (text with \\n line ends, encoding, the file's own line ending).  Keeps a UTF-8
    BOM (Windows PowerShell 5.1 needs it) and the file's CRLF / LF style."""
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        text, encoding = data[3:].decode("utf-8", "replace"), "utf-8-sig"
    else:
        try:
            text, encoding = data.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            encoding = "mbcs" if os.name == "nt" else "latin-1"
            text = data.decode(encoding, "replace")
    newline = "\r\n" if "\r\n" in text else "\n" if "\n" in text else _default_newline(path)
    return text.replace("\r\n", "\n"), encoding, newline


def _strip_block(text: str) -> str:
    lines, out, inside = text.splitlines(keepends=True), [], False
    for line in lines:
        if line.startswith(BEGIN):
            inside = True
            continue
        if inside:
            if line.startswith(END):
                inside = False
            continue
        out.append(line)
    return "".join(out)


def is_installed(target: Target) -> bool:
    try:
        return BEGIN in target.path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return False


def install(target: Target, python: str | None = None) -> str:
    python = python or sys.executable
    block = snippet(target.key, python)
    target.path.parent.mkdir(parents=True, exist_ok=True)
    if target.whole_file:
        target.path.write_text(block + "\n", encoding="utf-8", newline="\n")
        if target.system:
            target.path.chmod(0o755)
        return f"wrote {target.path}"
    if target.path.exists():
        text, encoding, newline = _read(target.path)
    else:
        text, encoding = "", "utf-8-sig" if target.path.suffix == ".ps1" else "utf-8"
        newline = _default_newline(target.path)
    text = _strip_block(text).rstrip("\n")
    text = (text + "\n\n" if text else "") + block + "\n"
    with open(target.path, "w", encoding=encoding, newline=newline) as f:
        f.write(text)
    return f"added hook to {target.path}"


def uninstall(target: Target) -> str:
    if not target.path.exists():
        return f"{target.path} does not exist"
    if target.whole_file:
        if is_installed(target):
            target.path.unlink()
            return f"removed {target.path}"
        return f"{target.path} was not written by hothello; left alone"
    text, encoding, newline = _read(target.path)
    if BEGIN not in text:
        return f"no hook in {target.path}"
    cleaned = _strip_block(text).rstrip("\n")
    with open(target.path, "w", encoding=encoding, newline=newline) as f:
        f.write(cleaned + ("\n" if cleaned else ""))
    return f"removed hook from {target.path}"


def seed_system_home() -> None:
    """Copy the invoking user's config (the one who ran sudo) into the
    system-wide home used by update-motd.d."""
    dest = Path(SYSTEM_HOME)
    dest.mkdir(parents=True, exist_ok=True)
    src_dir = paths.config_dir()
    if sudo_user := os.environ.get("SUDO_USER"):
        src_dir = Path(os.path.expanduser(f"~{sudo_user}")) / ".config" / paths.APP
    if (src_dir / "config.json").exists():
        shutil.copyfile(src_dir / "config.json", dest / "config.json")
    if (src_dir / "themes").is_dir():
        shutil.copytree(src_dir / "themes", dest / "themes", dirs_exist_ok=True)


# ~/.hushlogin makes sshd and login(1) skip the system MOTD and "Last login" line,
# so only hothello greets you.  Only files hothello created are ever removed.
HUSH_MARK = "# created by hothello\n"


def hushlogin_path() -> Path:
    return Path.home() / ".hushlogin"


def hushlogin_enabled() -> bool:
    return hushlogin_path().exists()


def set_hushlogin(on: bool) -> str:
    path = hushlogin_path()
    if on:
        if path.exists():
            return f"{path} already exists"
        path.write_text(HUSH_MARK, encoding="utf-8")
        return f"created {path}: the system login message is hidden"
    if not path.exists():
        return f"{path} does not exist"
    if path.read_text(encoding="utf-8", errors="replace") != HUSH_MARK:
        return f"{path} was not created by hothello; left alone"
    path.unlink()
    return f"removed {path}: the system login message is back"
