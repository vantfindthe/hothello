"""ASCII art from the top headline's picture."""

import io
import sqlite3
import time
import zlib

import pytest
from conftest import make_art

from hothello import motd, newsart, refresh
from hothello.feeds import parse_feed
from hothello.store import Store
from hothello.textutil import strip_ansi

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

FEED = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>Pics</title>
<item><title>Thumb</title><link>https://ex.com/1</link><media:thumbnail width="240" url="https://img.ex.com/t.jpg"/></item>
<item><title>Sizes</title><link>https://ex.com/2</link>
  <media:content width="140" url="https://img.ex.com/small.jpg"/>
  <media:content width="460" url="https://img.ex.com/big.jpg"/></item>
<item><title>Enclosure</title><link>https://ex.com/3</link><enclosure url="https://img.ex.com/e.png" type="image/png"/></item>
<item><title>Podcast</title><link>https://ex.com/4</link><enclosure url="https://ex.com/a.mp3" type="audio/mpeg"/></item>
<item><title>Inline</title><link>https://ex.com/5</link>
  <content:encoded><![CDATA[<p>Hi</p><img alt="x" src="https://img.ex.com/inline.jpg?a=1&amp;b=2"/>]]></content:encoded></item>
</channel></rss>"""

ATOM = b"""<feed xmlns="http://www.w3.org/2005/Atom"><title>A</title>
<entry><title>E</title><link href="https://ex.com/e"/><link rel="enclosure" type="image/jpeg" href="https://img.ex.com/a.jpg"/></entry>
</feed>"""


def test_feed_images():
    _, items = parse_feed(FEED)
    assert [i.image for i in items] == [
        "https://img.ex.com/t.jpg", "https://img.ex.com/big.jpg", "https://img.ex.com/e.png",
        None, "https://img.ex.com/inline.jpg?a=1&b=2",
    ]
    assert parse_feed(ATOM)[1][0].image == "https://img.ex.com/a.jpg"


def test_page_image():
    page = '<head><meta property="og:image" content="/img/lead.jpg"><meta name="twitter:image" content="x"></head>'
    assert newsart.page_image(page, "https://news.ex.com/story/1") == "https://news.ex.com/img/lead.jpg"
    assert newsart.page_image('<meta name="twitter:image" content="https://i.ex.com/t.png">', "https://e") \
        == "https://i.ex.com/t.png"
    assert newsart.page_image("<head><title>no picture</title></head>", "https://e") is None


def png(w: int = 300, h: int = 150) -> bytes:
    """A left-to-right dark-to-light gradient with a red square in the middle."""
    im = Image.new("RGB", (w, h))
    im.putdata([(x * 255 // w,) * 3 for y in range(h) for x in range(w)])
    im.paste((220, 30, 30), (w // 2 - 20, h // 2 - 20, w // 2 + 20, h // 2 + 20))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def test_prepare_and_render():
    w, h, packed = newsart.prepare(png())
    assert (w, h) == (160, 80)
    pixels = zlib.decompress(packed)
    lines, fg, bg = newsart.render(pixels, w, h, max_w=60, max_h=12)
    assert len(lines) <= 12 and max(len(line) for line in lines) <= 60
    assert bg is None and len(fg) == len(lines)
    assert lines[6].startswith(" ") and lines[6].rstrip().endswith("@")  # dark left, bright right
    lines_light, *_ = newsart.render(pixels, w, h, max_w=60, max_h=12, light_background=True)
    assert lines_light[6][0] == "@"  # inverted for light themes
    blocks, fg, bg = newsart.render(pixels, w, h, max_w=40, max_h=None, style="blocks")
    assert set("".join(blocks)) == {"▀"} and len(bg) == len(blocks)


def test_fit_keeps_the_shape():
    assert newsart.fit(160, 80, 64, None) == (64, 16)  # cells are about twice as tall as wide
    assert newsart.fit(160, 80, 64, 8) == (32, 8)
    assert newsart.fit(160, 80, 200, None, cap_w=40) == (40, 10)


@pytest.fixture
def news_store(store):
    now = time.time()
    store.replace_headlines("https://feeds.npr.org/1001/rss.xml", [
        ("Top story", "https://npr.org/top", now - 60, "https://img.npr.org/top.jpg"),
        ("Second", "https://npr.org/2", now - 600, None),
    ], now)
    store.upsert_art([make_art(1, 20, 5)])
    return store


def test_build_uses_the_picture(news_store, cfg):
    cfg["art"]["source"] = "news"
    cfg["news"]["feeds"] = ["npr"]
    w, h, packed = newsart.prepare(png())
    news_store.put_picture("https://npr.org/top", image_url="u", width=w, height=h, pixels=packed, when=time.time())
    res = motd.build(cfg, news_store, cols=100, rows=40, color="truecolor", glyphs="unicode", hyperlinks=True,
                     dry_run=True, measured=None)
    assert res.pick.art.url == "https://npr.org/top"
    text = strip_ansi(res.text)
    assert "Top story" in text and "npr.org" in text and "NPR News" in text
    assert "\x1b]8;;https://npr.org/top" in res.text  # the credit links to the article
    reds = [c for row in res.pick.art.fg for c in row if c[0] > 150 and c[1] < 90 and c[2] < 90]
    assert reds and any(f"38;2;{r};{g};{b}m" in res.text for r, g, b in reds)  # the picture's own colours


def test_falls_back_to_the_collection(news_store, cfg):
    cfg["art"]["source"] = "news"
    cfg["news"]["feeds"] = ["npr"]
    news_store.put_picture("https://npr.org/top", image_url=None, error="no picture", when=time.time())
    res = motd.build(cfg, news_store, cols=100, rows=40, color="none", dry_run=True, measured=None)
    assert res.pick.art.id == 1 and res.pick.art.url is None


def test_refresh_downloads_and_falls_back_to_the_article_page(news_store, cfg, monkeypatch):
    cfg["art"]["source"] = "news"
    cfg["news"]["feeds"] = ["npr"]
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        if url == "https://npr.org/2":
            return b'<meta property="og:image" content="https://img.npr.org/og.png">'
        return png()

    from hothello import net

    monkeypatch.setattr(net, "get", fake_get)
    refresh.refresh_pictures(cfg, news_store, log=lambda m: None)
    assert calls == ["https://img.npr.org/top.jpg", "https://npr.org/2", "https://img.npr.org/og.png"]
    assert news_store.get_picture("https://npr.org/top")["pixels"] is not None
    assert news_store.get_picture("https://npr.org/2")["image_url"] == "https://img.npr.org/og.png"
    calls.clear()
    refresh.refresh_pictures(cfg, news_store, log=lambda m: None)
    assert calls == []  # already cached: nothing downloaded again


def test_old_caches_gain_the_image_column(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE headlines (feed TEXT, title TEXT, link TEXT, published REAL, fetched_at REAL,"
                " PRIMARY KEY (feed, link))")
    con.commit()
    con.close()
    s = Store(db)
    assert "image" in {r[1] for r in s.db.execute("PRAGMA table_info(headlines)")}


def test_picture_switch(capsys):
    from hothello import cli, config

    assert cli.main(["on", "picture"]) == 0
    assert config.load()["art"]["source"] == "news"
    assert cli.main(["picture", "--style", "blocks", "--color", "theme", "--width", "50"]) == 0
    art = config.load()["art"]
    assert (art["picture_style"], art["picture_color"], art["picture_width"]) == ("blocks", "theme", 50)
    assert cli.main(["picture", "off"]) == 0
    assert config.load()["art"]["source"] == "collection"
