from motdplus.feeds import Feed, enabled_feeds, parse_date, parse_feed, select_headlines

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Example News</title>
<item><title>First &amp;amp; foremost</title><link>https://example.com/1</link>
<pubDate>Tue, 29 Sep 2026 04:00:00 GMT</pubDate></item>
<item><title><![CDATA[<b>Bold</b> move]]></title><link></link><guid isPermaLink="true">https://example.com/2</guid></item>
<item><title>Evil \x1b]0;pwned\x07 title</title><link>https://example.com/3</link></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom Site</title>
<entry><title type="html">Atom entry</title>
<link rel="self" href="https://example.com/self"/><link rel="alternate" href="https://example.com/a"/>
<updated>2026-09-28T10:00:00Z</updated></entry></feed>"""

RDF = b"""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel><title>RDF Feed</title></channel>
<item><title>RDF item</title><link>https://example.com/r</link><dc:date>2026-09-28T12:00:00+02:00</dc:date></item>
</rdf:RDF>"""

HTML_ENTITIES = b"""<rss><channel><title>Sloppy</title>
<item><title>Caf&eacute; &nbsp; &rsquo;quoted&rsquo;</title><link>https://example.com/s</link></item>
</channel></rss>"""


def test_rss():
    title, items = parse_feed(RSS.replace(b"\x1b", b"").replace(b"\x07", b""))
    assert title == "Example News"
    assert items[0].title == "First & foremost"
    assert items[0].published == parse_date("2026-09-29T04:00:00Z")
    assert items[1].title == "Bold move"
    assert items[1].link == "https://example.com/2"


def test_atom_prefers_alternate_link():
    title, items = parse_feed(ATOM)
    assert title == "Atom Site"
    assert items[0].link == "https://example.com/a"
    assert items[0].published == parse_date("2026-09-28T10:00:00+00:00")


def test_rdf():
    title, items = parse_feed(RDF)
    assert title == "RDF Feed"
    assert items[0].title == "RDF item"
    assert items[0].published is not None


def test_html_entities_are_tolerated():
    _, items = parse_feed(HTML_ENTITIES)
    assert items[0].title == "Café ’quoted’"


def test_parse_date_bad_input():
    assert parse_date("not a date") is None
    assert parse_date("") is None


def rows(feed, n, start=1000.0):
    return [{"feed": feed, "title": f"{feed} {i}", "link": f"https://{feed}/{i}",
             "published": start - i * 60, "fetched_at": start} for i in range(n)]


def test_select_interleaves_sources_and_caps():
    feeds = [Feed("a", "Alpha", "A"), Feed("b", "Beta", "B")]
    out = select_headlines(rows("a", 5, 2000) + rows("b", 5, 1000), feeds,
                           count=5, per_source=2, max_age_hours=0, now=2000)
    assert [h.badge for h in out] == ["A", "B", "A", "B"]  # per_source=2 caps at 4


def test_select_drops_stale_and_duplicates():
    feeds = [Feed("a", "Alpha", "A"), Feed("b", "Beta", "B")]
    fresh = rows("a", 2, 100_000)
    dup = [dict(fresh[0], feed="b", link="https://b/x")]
    stale = rows("b", 2, 1_000)
    out = select_headlines(fresh + dup + stale, feeds, count=10, per_source=5, max_age_hours=1, now=100_000)
    assert [h.title for h in out] == ["a 0", "a 1"]


def test_enabled_feeds_merges_presets_and_custom():
    feeds = enabled_feeds({"feeds": ["npr", "nope"], "custom": [
        {"name": "Mine", "url": "https://me/feed", "enabled": True},
        {"name": "Off", "url": "https://off/feed", "enabled": False},
    ]})
    assert [f.name for f in feeds] == ["NPR News", "Mine"]
