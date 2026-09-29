from hothello import render, sysstat, themes
from hothello.sysstat import UTMP_RECORD, SysInfo, parse_meminfo, parse_updates, read_utmp
from hothello.textutil import visible_width

UPDATES = """
Expanded Security Maintenance for Applications is not enabled.

34 updates can be applied immediately.
4 of these updates are standard security updates.
To see these additional updates run: apt list --upgradable

8 additional security updates can be applied with ESM Apps.
Learn more about enabling ESM Apps service at https://ubuntu.com/esm
"""


def test_parse_updates():
    assert parse_updates(UPDATES) == (34, 4, 8)
    assert parse_updates("1 update can be applied immediately.\n1 of these updates is a standard security update.") == (1, 1, None)
    assert parse_updates("0 updates can be applied immediately.") == (0, None, None)
    assert parse_updates("") == (None, None, None)


def test_parse_meminfo():
    memory, swap = parse_meminfo("MemTotal: 1000 kB\nMemFree: 100 kB\nMemAvailable: 400 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n")
    assert memory == (600 * 1024, 1000 * 1024)
    assert swap is None


def record(kind: int, user: str, line: str, host: str, when: int) -> bytes:
    return UTMP_RECORD.pack(kind, 123, line.encode(), b"ts/0", user.encode(), host.encode(),
                            0, 0, 0, when, 0, 0, 0, 0, 0, b"")


def test_read_utmp_and_last_login(monkeypatch):
    data = b"".join([
        record(7, "deploy", "pts/0", "1.2.3.4", 100),
        record(8, "", "pts/0", "", 150),  # logout record
        record(7, "deploy", "pts/1", "tmux(99).%0", 180),  # tmux panes are not logins
        record(7, "deploy", "pts/2", "5.6.7.8", 200),
        record(7, "root", "tty1", "", 250),
    ])
    assert UTMP_RECORD.size == 384
    assert read_utmp(data)[0] == ("deploy", "pts/0", "1.2.3.4", 100)
    monkeypatch.setattr(sysstat, "_utmp_tail", lambda path, records=400: data)
    assert sysstat.last_login("deploy", "pts/2") == (100.0, "1.2.3.4")  # pts/2 is this session
    assert sysstat.last_login("deploy", None) == (200.0, "5.6.7.8")
    assert sysstat.last_login("nobody", None) is None


INFO = SysInfo(
    load=(0.01, 0.05, 0.0), disk=(25 * 2**30, 290 * 2**30), memory=(2 * 2**30, 24 * 2**30),
    swap=(0, 4 * 2**30), processes=280, users=2,
    addresses=[("eth0", "192.0.2.10"), ("eth0", "2001:db8::10")],
    updates=34, security=4, esm=8, restart=True, restart_pkgs=["linux-image-6.8.0-142-generic", "linux-base"],
    last_login=(1_790_000_000.0, "203.0.113.7"),
)
CFG = {"enabled": True, "items": list(sysstat.ITEMS), "alerts": True, "last_login": True, "bars": True}


def test_system_block_fits_and_says_the_important_things():
    theme = themes.get_theme("tokyo-night")
    for glyphs in ("nerd", "unicode", "ascii"):
        for cols in (39, 79, 119, 199):
            lines = render.system_block(INFO, CFG, theme, themes.GLYPH_SETS[glyphs], themes.Painter("truecolor"), cols)
            assert max(visible_width(line) for line in lines) <= cols, (glyphs, cols)
            plain = "\n".join(render.system_block(INFO, CFG, theme, themes.GLYPH_SETS[glyphs], themes.Painter("none"), cols))
            assert "System restart required" in plain
            assert "34 updates" in plain
            assert "Last login" in plain
    wide = render.system_block(INFO, CFG, theme, themes.GLYPH_SETS["unicode"], themes.Painter("none"), 119)
    assert len(wide) < len(render.system_block(INFO, CFG, theme, themes.GLYPH_SETS["unicode"], themes.Painter("none"), 39))


def test_system_block_can_be_alerts_only():
    theme = themes.get_theme("mono")
    lines = render.system_block(INFO, {**CFG, "items": []}, theme, themes.GLYPH_SETS["ascii"], themes.Painter("none"), 80)
    assert lines[0].startswith("System")
    assert not any("Load" in line for line in lines)
    assert any("restart" in line for line in lines)


def test_nothing_to_say_means_no_section():
    theme = themes.get_theme("mono")
    empty = {**CFG, "items": [], "alerts": False, "last_login": False}
    assert render.system_block(SysInfo(), empty, theme, themes.GLYPH_SETS["ascii"], themes.Painter("none"), 80) == []


def test_tiny_screens_keep_the_art_and_one_alert_line(store, cfg, monkeypatch):
    from conftest import make_art

    from hothello import motd
    from hothello.textutil import strip_ansi

    monkeypatch.setattr(sysstat, "gather", lambda c: INFO)
    store.upsert_art([make_art(1, 20, 4)])
    res = motd.build(cfg, store, cols=40, rows=13, color="truecolor", glyphs="unicode", dry_run=True, measured=None)
    text = strip_ansi(res.text)
    assert res.pick.art is not None
    assert "restart required" in text and "System" not in text  # folded into one line
    assert len(text.rstrip("\n").split("\n")) + cfg["display"]["reserve_rows"] <= 13


def test_gather_on_this_machine_does_not_raise():
    info = sysstat.gather(CFG)
    assert isinstance(info, SysInfo)
