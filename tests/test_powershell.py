"""The PowerShell login hook, run in a real PowerShell when one is installed."""

import os
import shutil
import subprocess
import sys

import pytest

from hothello import hooks, sysstat

SHELLS = [s for s in ("powershell", "pwsh") if shutil.which(s)]
needs_powershell = pytest.mark.skipif(not SHELLS, reason="needs PowerShell")


def ps(shell: str, *args: str, env=None) -> str:
    proc = subprocess.run([shutil.which(shell), "-NoProfile", "-NoLogo", *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=120, env=env)
    return proc.stdout + proc.stderr


@pytest.fixture
def profile(tmp_path):
    path = tmp_path / "profile.ps1"
    path.write_text(hooks.snippet("powershell", sys.executable) + "\n", encoding="utf-8-sig")
    return path


@needs_powershell
@pytest.mark.parametrize("shell", SHELLS)
def test_snippet_parses(shell, profile):
    out = ps(shell, "-Command", "$e = $null; [System.Management.Automation.Language.Parser]::ParseFile("
             f"'{profile}', [ref]$null, [ref]$e) | Out-Null; 'errors=' + $e.Count")
    assert "errors=0" in out


@needs_powershell
@pytest.mark.parametrize("shell", SHELLS)
def test_greets_interactive_sessions_only(shell, profile, tmp_path):
    env = {**os.environ, "HOTHELLO_HOME": str(tmp_path / "home"), "PYTHONPATH": "keep-me",
           "HOTHELLO_SHOWN": ""}
    env.pop("HOTHELLO_SHOWN")
    interactive = ps(shell, "-NoExit", "-Command",
                     f". '{profile}'; 'PYTHONPATH=' + $env:PYTHONPATH; exit", env=env)
    assert "No art cached yet" in interactive  # the greeting ran (empty cache)
    assert "PYTHONPATH=keep-me" in interactive  # and put PYTHONPATH back
    script = ps(shell, "-Command", f". '{profile}'; 'done'", env=env)
    assert "No art cached yet" not in script and "done" in script
    non_interactive = ps(shell, "-NonInteractive", "-NoExit", "-Command", f". '{profile}'; 'done'; exit", env=env)
    assert "No art cached yet" not in non_interactive


@needs_powershell
@pytest.mark.parametrize("shell", SHELLS)
def test_hothello_command_inside_powershell(shell, profile, tmp_path):
    env = {**os.environ, "HOTHELLO_HOME": str(tmp_path / "home")}
    out = ps(shell, "-Command", f". '{profile}'; hothello --version", env=env)
    assert "hothello " in out


@pytest.mark.parametrize("eol", [b"\r\n", b"\n"])
def test_install_into_a_ps1_profile_round_trips(tmp_path, eol):
    profile = tmp_path / "profile.ps1"
    lines = [b"Import-Module posh-git", b"", b"oh-my-posh init pwsh --config 'takuya' | Invoke-Expression"]
    original = b"\xef\xbb\xbf" + eol.join(lines) + eol  # saved with a BOM
    profile.write_bytes(original)
    target = hooks.Target("powershell", "Windows PowerShell", profile)
    hooks.install(target, r"C:\py\python.exe")
    hooks.install(target, r"C:\py\python.exe")
    data = profile.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")  # Windows PowerShell 5.1 needs the BOM kept
    assert data.count(hooks.BEGIN.encode()) == 1
    assert b"\r\r" not in data
    if eol == b"\r\n":
        assert b"\n" not in data.replace(b"\r\n", b"")  # the file's own line ending, throughout
    else:
        assert b"\r" not in data
    hooks.uninstall(target)
    assert profile.read_bytes() == original


@pytest.mark.skipif(os.name != "nt", reason="Windows only")
def test_windows_system_facts():
    info = sysstat.gather({"items": list(sysstat.ITEMS), "alerts": True, "last_login": True})
    assert info.disk_label.endswith(":") and info.disk
    assert info.processes and info.processes > 1
    assert info.memory


def test_primary_addresses_skip_loopback():
    for _, addr in sysstat.primary_addresses():
        assert not addr.startswith(("127.", "::1"))
