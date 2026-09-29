import json
import subprocess
import sys

from hothello import cli, hooks, themes
from hothello.hooks import BEGIN, END, Target


def test_install_is_idempotent_and_reversible(tmp_path):
    rc = tmp_path / ".bashrc"
    rc.write_text("# mine\nalias ll='ls -l'\n")
    target = Target("bash", "bash", rc)
    hooks.install(target, "/usr/bin/python3")
    hooks.install(target, "/usr/bin/python3")
    text = rc.read_text()
    assert text.count(BEGIN) == 1 and text.count(END) == 1
    assert "alias ll='ls -l'" in text
    assert hooks.is_installed(target)
    hooks.uninstall(target)
    assert rc.read_text() == "# mine\nalias ll='ls -l'\n"


def test_bash_snippet_is_valid_and_guarded(tmp_path):
    rc = tmp_path / "rc"
    rc.write_text(hooks.snippet("bash", "/nonexistent/python it's") + "\n")
    subprocess.run(["bash", "-n", str(rc)], check=True)  # syntax check
    # non-interactive shells never run it
    out = subprocess.run(["bash", "-c", f"source {rc}; echo done"], capture_output=True, text=True)
    assert out.stdout == "done\n"


def test_powershell_snippet_quotes_paths():
    s = hooks.snippet("powershell", "C:\\Users\\o'brien\\python.exe")
    assert "'C:\\Users\\o''brien\\python.exe'" in s


def test_hushlogin_only_removes_our_file(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks.Path, "home", staticmethod(lambda: tmp_path))
    hooks.set_hushlogin(True)
    assert hooks.hushlogin_enabled()
    hooks.set_hushlogin(False)
    assert not hooks.hushlogin_enabled()
    (tmp_path / ".hushlogin").write_text("")
    assert "left alone" in hooks.set_hushlogin(False)
    assert hooks.hushlogin_enabled()


OMP = {
    "palette": {"blue": "#0077c2"},
    "blocks": [{"segments": [
        {"background": "p:blue", "foreground": "#ffffff", "leading_diamond": "\ue0b6"},
        {"background": "#ef5350", "foreground": "#FFFB38", "powerline_symbol": "\ue0b0"},
        {"background": "transparent", "foreground": "#3C873A"},
        {"background": "#444444", "foreground": "lightYellow"},
    ]}],
}


def test_import_omp_from_file(tmp_path):
    path = tmp_path / "mine.omp.json"
    path.write_text(json.dumps(OMP), encoding="utf-8")
    theme = themes.import_omp(str(path))
    assert theme.key == "omp-mine"
    assert theme.separator == "round"
    assert theme.segments[:2] == [["#0077c2", "#ffffff"], ["#ef5350", "#FFFB38"]]
    assert theme.segments[2] == ["#444444", "bright_yellow"]
    assert theme.frame == "#444444"  # the grey segment
    assert themes.get_theme("omp-mine").segments == theme.segments  # saved as a user theme


def test_show_never_raises(monkeypatch, capsys):
    import hothello.motd as m

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(m, "build", boom)
    assert cli.main(["show", "--no-refresh"]) == 0


def test_show_cli_runs(capsys):
    assert cli.main(["show", "--no-refresh", "--width", "80", "--height", "24", "--color", "none"]) == 0
    out = capsys.readouterr().out
    assert "No art cached yet" in out


def test_closed_pipe_is_not_an_error():
    proc = subprocess.run(f"{sys.executable} -m hothello features | head -1", shell=True,
                          capture_output=True, text=True)
    assert proc.stdout.startswith("Features")
    assert "Traceback" not in proc.stderr and "BrokenPipe" not in proc.stderr


def test_module_entry_point():
    out = subprocess.run([sys.executable, "-m", "hothello", "--version"], capture_output=True, text=True)
    assert out.stdout.startswith("hothello ")
