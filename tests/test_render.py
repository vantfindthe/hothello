import itertools
import time

import pytest
from conftest import make_art

from motdplus import motd, themes
from motdplus.render import hyperlink
from motdplus.textutil import strip_ansi, visible_width


@pytest.fixture
def filled(store):
    store.upsert_art([make_art(i, w, h, title="A rather long title for a small piece")
                      for i, (w, h) in enumerate([(8, 4), (30, 10), (70, 20), (120, 40)], 1)])
    now = time.time()
    store.replace_headlines("https://feeds.npr.org/1001/rss.xml",
                            [(f"Headline number {i} " + "word " * 30, f"https://n/{i}", now - i * 600) for i in range(6)], now)
    return store


SIZES = [(40, 12), (64, 20), (80, 24), (120, 32), (200, 60)]


@pytest.mark.parametrize("theme,glyphs,color", list(itertools.product(
    ["tokyo-night", "classic", "synthwave", "mono"], ["nerd", "unicode", "ascii"], ["truecolor", "16", "none"])))
def test_output_fits_every_screen(filled, cfg, theme, glyphs, color):
    cfg["theme"]["name"] = theme
    for cols, rows in SIZES:
        res = motd.build(cfg, filled, cols=cols, rows=rows, color=color, glyphs=glyphs,
                         hyperlinks=True, dry_run=True, measured=None)
        lines = res.text.rstrip("\n").split("\n")
        assert max(visible_width(line) for line in lines) < cols, (cols, rows)
        assert len(lines) + cfg["display"]["reserve_rows"] <= rows, (cols, rows)
        if color == "none":
            assert "\x1b[" not in res.text


def test_short_screens_trade_headlines_for_art(filled, cfg):
    res = motd.build(cfg, filled, cols=40, rows=16, color="none", dry_run=True, measured=None)
    assert res.pick.art is not None
    assert len(res.plan.headlines) < 5


def test_no_frame_has_credit_line(filled, cfg):
    cfg["display"]["frame"] = "none"
    res = motd.build(cfg, filled, cols=100, rows=40, color="none", dry_run=True, measured=None)
    assert "asciiart.website/art/" in res.text


def test_ascii_glyphs_are_ascii(filled, cfg):
    res = motd.build(cfg, filled, cols=100, rows=40, color="none", glyphs="ascii", hyperlinks=False,
                     dry_run=True, measured=None)
    assert res.text.isascii()


def test_first_run_notice(store, cfg):
    res = motd.build(cfg, store, cols=80, rows=24, color="none", dry_run=True, measured=None)
    assert "No art cached yet" in res.text


def test_hyperlink_refuses_other_schemes():
    assert hyperlink("x", "javascript:alert(1)", True) == "x"
    assert hyperlink("x", "https://a.b/\x1b]evil", True) == "\x1b]8;;https://a.b/]evil\x1b\\x\x1b]8;;\x1b\\"
    assert strip_ansi(hyperlink("text", "https://a.b", True)) == "text"


def test_resolve_size_modes():
    d = {"size": "classic", "width": 100, "height": 30}
    assert motd.resolve_size(d, (200, 50)) == (80, 24)
    assert motd.resolve_size(d, (60, 50)) == (60, 24)  # never wider than the window
    assert motd.resolve_size({**d, "size": "auto"}, (120, 40)) == (120, 40)
    assert motd.resolve_size({**d, "size": "auto"}, None) == (100, 30)
    assert motd.resolve_size({**d, "size": "auto-width"}, (120, 40)) == (120, None)
    assert motd.resolve_size({**d, "size": "custom"}, None) == (100, 30)


def test_colour_conversion():
    assert themes.rgb_to_256((255, 0, 0)) == 196
    assert themes.rgb_to_256((128, 128, 128)) in (244, 102)
    assert themes.rgb_to_16((250, 250, 250)) == 15
    assert themes.parse_color("#abc") == ("rgb", (0xAA, 0xBB, 0xCC))
    assert themes.parse_color("bright_red") == ("ansi", 9)
    assert themes.parse_color("nonsense") is None


def test_every_builtin_theme_renders(filled, cfg):
    for key in themes.BUILTIN_THEMES:
        cfg["theme"]["name"] = key
        res = motd.build(cfg, filled, cols=100, rows=40, color="truecolor", glyphs="nerd", dry_run=True, measured=None)
        assert res.pick.art is not None
