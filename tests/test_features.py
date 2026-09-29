import io
import re
import time

import pytest
from conftest import make_art

from motdplus import animate, cli, config, motd, sysinfo, themes
from motdplus.textutil import strip_ansi


@pytest.fixture
def filled(store):
    store.upsert_art([make_art(i, w, h, title=f"Piece {i}") for i, (w, h) in enumerate([(12, 5), (30, 8)], 1)])
    now = time.time()
    store.replace_headlines("https://feeds.npr.org/1001/rss.xml",
                            [(f"Headline {i}", f"https://n/{i}", now - i * 600) for i in range(3)], now)
    return store


def run(*argv) -> int:
    return cli.main(list(argv))


# -- feature switches ---------------------------------------------------------------------------

def test_on_off_toggle(capsys):
    assert run("off", "headlines", "credit", "names") == 0
    cfg = config.load()
    assert cfg["news"]["enabled"] is False
    assert cfg["display"]["credit"] is False and cfg["display"]["title"] is False
    assert run("toggle", "news") == 0
    assert config.load()["news"]["enabled"] is True
    assert run("hide", "ip") == 0
    assert "network" not in config.load()["system"]["items"]
    assert run("on", "ips") == 0
    assert config.load()["system"]["items"][-1] == "network"
    assert run("off", "nonsense") == 1


def test_value_features_remember_what_they_were():
    run("frame", "double")
    run("off", "frame")
    assert config.load()["display"]["frame"] == "none"
    run("on", "frame")
    assert config.load()["display"]["frame"] == "double"
    run("off", "animation")
    run("on", "animation")
    assert config.load()["animation"]["style"] == "random"  # nothing to restore: pick the default


def test_features_list(capsys):
    assert run("features") == 0
    out = capsys.readouterr().out
    for name in ("headlines", "credit", "title", "privacy", "animation", "network"):
        assert name in out


# -- privacy -------------------------------------------------------------------------------------

def test_privacy_hides_identifying_details(filled, cfg, monkeypatch):
    cfg["theme"]["segments"] = ["greeting", "user", "host", "os", "kernel", "uptime", "datetime"]
    cfg["privacy"]["alias"] = "streamer"
    normal = motd.build(cfg, filled, cols=120, rows=60, color="none", dry_run=True, measured=None)
    private = motd.build(cfg, filled, cols=120, rows=60, color="none", dry_run=True, measured=None, private=True)
    host, kernel = sysinfo.host(), sysinfo.platform.release()
    assert host in normal.text
    for secret in (host, kernel, sysinfo.user(), "Last login", " of ", "restart", "updates can"):
        assert secret not in private.text, secret
    assert "streamer" in private.text
    assert not re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", private.text)
    monkeypatch.setenv("MOTDPLUS_PRIVACY", "1")
    assert motd.build(cfg, filled, cols=120, rows=60, color="none", dry_run=True, measured=None).private


def test_privacy_command(capsys):
    assert run("privacy", "on", "--alias", "anon") == 0
    assert config.load()["privacy"] == {"enabled": True, "alias": "anon"}


# -- art name / source ---------------------------------------------------------------------------

def test_title_and_credit_switches(filled, cfg):
    cfg["display"]["title"] = False
    text = motd.build(cfg, filled, cols=100, rows=40, color="none", dry_run=True, measured=None).text
    assert "Piece " not in text and "asciiart.website" in text
    cfg["display"]["title"], cfg["display"]["credit"] = True, False
    text = motd.build(cfg, filled, cols=100, rows=40, color="none", dry_run=True, measured=None).text
    assert "Piece " in text and "asciiart.website" not in text
    cfg["display"]["frame"] = "none"
    cfg["display"]["title"] = False
    text = motd.build(cfg, filled, cols=100, rows=40, color="none", dry_run=True, measured=None).text
    assert "Piece " not in text and "asciiart.website" not in text


# -- list / set commands -----------------------------------------------------------------------------

@pytest.mark.parametrize("argv", [["theme"], ["font"], ["color"], ["frame"], ["size"], ["cycle"],
                                  ["animation"], ["feeds"], ["headlines"], ["greeting"], ["categories"],
                                  ["privacy"], ["get"], ["get", "display.width"]])
def test_listings_run(argv, store, capsys):
    assert run(*argv) == 0
    assert capsys.readouterr().out.strip()


def test_setters(capsys):
    assert run("theme", "gruv") == 0  # unique prefix of gruvbox
    assert run("font", "ascii") == 0
    assert run("color", "256") == 0
    assert run("size", "100x30") == 0
    assert run("cycle", "rotate", "--every", "daily", "--prefer", "large") == 0
    assert run("animation", "nuke", "--speed", "fast", "--target", "art") == 0
    assert run("headlines", "--count", "3") == 0
    assert run("greeting", "Hi", "{user}") == 0
    cfg = config.load()
    assert cfg["theme"]["name"] == "gruvbox" and cfg["theme"]["glyphs"] == "ascii"
    assert cfg["theme"]["color"] == "256" and cfg["theme"]["greeting"] == "Hi {user}"
    assert (cfg["display"]["size"], cfg["display"]["width"], cfg["display"]["height"]) == ("custom", 100, 30)
    assert (cfg["art"]["cycle"], cfg["art"]["change"], cfg["art"]["prefer"]) == ("rotate", "daily", "large")
    assert cfg["animation"] == {"style": "nuke", "speed": "fast", "target": "art"}
    assert cfg["news"]["count"] == 3
    assert run("theme", "nope") == 1


def test_categories_by_name_and_group(store, capsys):
    assert run("categories", "--add", "cats") == 0
    assert config.load()["art"]["categories"] == [1]
    assert run("categories", "--add", "Things") == 0  # a whole group
    assert config.load()["art"]["categories"] == [1, 3]
    assert run("categories", "--remove", "3") == 0
    assert run("categories", "--only", "dogs") == 0
    assert config.load()["art"]["categories"] == [2]
    assert run("categories", "--clear") == 0
    assert config.load()["art"]["categories"] == []


def test_set_get_reset(capsys):
    assert run("set", "display.width", "120") == 0
    assert config.load()["display"]["width"] == 120
    assert run("set", "display.width", "wide") == 1  # wrong type
    assert run("set", "theme.segments", '["greeting", "datetime"]') == 0
    assert run("set", "news.enabled", "off") == 0
    assert config.load()["news"]["enabled"] is False
    assert run("set", "no.such", "1") == 1
    assert run("reset") == 1  # needs --yes
    assert run("reset", "news", "--yes") == 0
    assert config.load()["news"]["enabled"] is True
    assert config.load()["display"]["width"] == 120


# -- animations ------------------------------------------------------------------------------------

def test_parse_line_tracks_colours_and_backgrounds():
    line = "\x1b[38;2;1;2;3mab\x1b[0m \x1b[44m x\x1b[0m\x1b]8;;https://e\x1b\\L\x1b]8;;\x1b\\"
    cells = animate.parse_line(line)
    assert cells[0] == animate.Cell("\x1b[38;2;1;2;3m", "a")
    assert 2 not in cells  # a plain space is not drawn
    assert cells[3] == animate.Cell("\x1b[44m", " ")  # a coloured-background space is
    assert cells[5].ch == "L" and cells[5].style == ""


@pytest.mark.parametrize("style", animate.EFFECTS)
def test_every_effect_ends_on_the_full_picture(style):
    _, grid = animate.parse("hello\n  \x1b[31mworld\x1b[0m\n\n!!")
    frames = list(animate.FX[style](grid, 20, width=40, height=4, painter=themes.Painter("truecolor"),
                                    ascii_only=False, rng=__import__("random").Random(1)))
    assert len(frames) == 20
    assert frames[-1] == grid
    for frame in frames:
        assert all(0 <= r < 4 and 0 <= c < 40 for r, c in frame)


class FakeTTY(io.StringIO):
    def isatty(self):
        return True


class MiniTerm:
    """Just enough of a VT100 to replay the animation output (ONLCR on, like a tty)."""

    def __init__(self, rows: int, cols: int, start_row: int):
        self.rows, self.cols = rows, cols
        self.grid = [[" "] * cols for _ in range(rows)]
        self.r, self.c = start_row, 0

    def feed(self, s: str) -> None:
        i = 0
        while i < len(s):
            if s[i] == "\x1b":
                m = re.match(r"\x1b\[([0-9;?]*)([A-Za-z])|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", s[i:])
                assert m, repr(s[i:i + 10])
                if m.group(2):
                    n = int(m.group(1)) if m.group(1).isdigit() else 1
                    if m.group(2) == "A":
                        self.r = max(0, self.r - n)
                    elif m.group(2) == "B":
                        self.r = min(self.rows - 1, self.r + n)
                    elif m.group(2) == "C":
                        self.c = min(self.cols - 1, self.c + n)
                    elif m.group(2) == "K":
                        self.grid[self.r][self.c:] = [" "] * (self.cols - self.c)
                i += len(m.group(0))
                continue
            ch = s[i]
            if ch == "\n":
                self.c = 0
                if self.r == self.rows - 1:
                    self.grid = self.grid[1:] + [[" "] * self.cols]
                else:
                    self.r += 1
            elif ch == "\r":
                self.c = 0
            else:
                self.grid[self.r][self.c] = ch
                self.c += 1
            i += 1

    def text(self, first: int, count: int) -> list[str]:
        return ["".join(row).rstrip() for row in self.grid[first:first + count]]


@pytest.mark.parametrize("style", animate.EFFECTS + ["random"])
@pytest.mark.parametrize("start_row", [2, 17])  # with room below, and near the bottom (forces a scroll)
def test_play_leaves_exactly_the_motd_on_screen(filled, cfg, style, start_row):
    res = motd.build(cfg, filled, cols=80, rows=20, color="truecolor", glyphs="unicode", hyperlinks=True,
                     dry_run=True, measured=None)
    out = FakeTTY()
    assert animate.play(res.text, style=style, width=res.plan.usable, term_rows=24,
                        painter=themes.Painter("truecolor"), out=out, realtime=False, seed=3,
                        focus=res.sections.get("art"))
    term = MiniTerm(24, 80, start_row)
    term.feed(out.getvalue())
    expected = [line.rstrip() for line in strip_ansi(res.text).rstrip("\n").split("\n")]
    top = term.r - len(expected)  # the cursor ends on the line after the MOTD
    assert term.text(top, len(expected)) == expected
    assert out.getvalue().endswith("\x1b[?25h")


def test_play_falls_back_to_plain_text():
    out = io.StringIO()  # not a terminal
    assert not animate.play("a\nb\n", style="nuke", width=40, term_rows=24, painter=themes.Painter("none"), out=out)
    assert out.getvalue() == "a\nb\n"
    tall = FakeTTY()
    assert not animate.play("x\n" * 30, style="rain", width=40, term_rows=24, painter=themes.Painter("none"), out=tall)


def test_only_animates_the_requested_lines(monkeypatch):
    frames = []
    real_draw = animate.Screen.draw

    def record(self, frame):
        frames.append({pos[0] for pos in frame})
        real_draw(self, frame)

    monkeypatch.setattr(animate.Screen, "draw", record)
    animate.play("header\n\nart\nart\n\nnews\n", style="lines", width=40, term_rows=24,
                 painter=themes.Painter("none"), out=FakeTTY(), realtime=False, only=(2, 4))
    assert {0, 5} <= frames[0]  # header and news are there from the first frame
    assert 3 not in frames[0]  # the art is still being revealed
    assert frames[-1] == {0, 2, 3, 5}
