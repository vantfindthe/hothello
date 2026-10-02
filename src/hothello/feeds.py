"""News headlines from RSS 2.0, RSS 1.0 (RDF) and Atom feeds (stdlib only)."""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from .textutil import sanitize


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    badge: str
    group: str
    url: str


# Every URL here was checked to serve a valid feed to a non-browser client.
PRESETS: list[Preset] = [
    Preset("bbc-world", "BBC News - World", "BBC", "World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    Preset("bbc-top", "BBC News - Top Stories", "BBC", "World", "https://feeds.bbci.co.uk/news/rss.xml"),
    Preset("guardian-world", "The Guardian - World", "Guardian", "World", "https://www.theguardian.com/world/rss"),
    Preset("aljazeera", "Al Jazeera", "AJ", "World", "https://www.aljazeera.com/xml/rss/all.xml"),
    Preset("dw", "Deutsche Welle", "DW", "World", "https://rss.dw.com/rdf/rss-en-all"),
    Preset("france24", "France 24", "France24", "World", "https://www.france24.com/en/rss"),
    Preset("lemonde", "Le Monde in English", "Le Monde", "World", "https://www.lemonde.fr/en/rss/une.xml"),
    Preset("skynews", "Sky News - World", "Sky", "World", "https://feeds.skynews.com/feeds/rss/world.xml"),
    Preset("csmonitor", "Christian Science Monitor", "CSM", "World", "https://rss.csmonitor.com/feeds/all"),
    Preset("npr", "NPR News", "NPR", "US", "https://feeds.npr.org/1001/rss.xml"),
    Preset("pbs", "PBS NewsHour", "PBS", "US", "https://www.pbs.org/newshour/feeds/rss/headlines"),
    Preset("nyt", "New York Times - Home Page", "NYT", "US", "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"),
    Preset("abc-us", "ABC News", "ABC", "US", "https://abcnews.go.com/abcnews/topstories"),
    Preset("cbs", "CBS News", "CBS", "US", "https://www.cbsnews.com/latest/rss/main"),
    Preset("propublica", "ProPublica", "ProPub", "US", "https://www.propublica.org/feeds/propublica/main"),
    Preset("cbc", "CBC News - Top Stories", "CBC", "Regional", "https://www.cbc.ca/webfeed/rss/rss-topstories"),
    Preset("abc-au", "ABC News (Australia)", "ABC AU", "Regional", "https://www.abc.net.au/news/feed/51120/rss.xml"),
    Preset("japantimes", "The Japan Times", "JT", "Regional", "https://www.japantimes.co.jp/feed/"),
    Preset("economist", "The Economist - Latest", "Economist", "Business", "https://www.economist.com/latest/rss.xml"),
    Preset("wsj-world", "Wall Street Journal - World", "WSJ", "Business", "https://feeds.a.dj.com/rss/RSSWorldNews.xml"),
    Preset("ft", "Financial Times", "FT", "Business", "https://www.ft.com/rss/home"),
    Preset("cnbc", "CNBC - Top News", "CNBC", "Business", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    Preset("ars", "Ars Technica", "Ars", "Tech", "https://feeds.arstechnica.com/arstechnica/index"),
    Preset("verge", "The Verge", "Verge", "Tech", "https://www.theverge.com/rss/index.xml"),
    Preset("wired", "Wired", "Wired", "Tech", "https://www.wired.com/feed/rss"),
    Preset("techcrunch", "TechCrunch", "TC", "Tech", "https://techcrunch.com/feed/"),
    Preset("hn", "Hacker News - Front Page", "HN", "Tech", "https://news.ycombinator.com/rss"),
    Preset("bbc-tech", "BBC News - Technology", "BBC Tech", "Tech", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    Preset("lwn", "LWN.net", "LWN", "Tech", "https://lwn.net/headlines/rss"),
    Preset("bleeping", "BleepingComputer", "Bleeping", "Tech", "https://www.bleepingcomputer.com/feed/"),
    Preset("krebs", "Krebs on Security", "Krebs", "Tech", "https://krebsonsecurity.com/feed/"),
    Preset("nature", "Nature", "Nature", "Science", "https://www.nature.com/nature.rss"),
    Preset("sciencedaily", "ScienceDaily", "SciDaily", "Science", "https://www.sciencedaily.com/rss/all.xml"),
    Preset("nasa", "NASA - News Releases", "NASA", "Science", "https://www.nasa.gov/news-release/feed/"),
    Preset("newscientist", "New Scientist", "NewSci", "Science", "https://www.newscientist.com/feed/home/"),
    Preset("bbc-science", "BBC News - Science", "BBC Sci", "Science", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
    Preset("guardian-science", "The Guardian - Science", "Guardian", "Science", "https://www.theguardian.com/science/rss"),
]
PRESETS_BY_ID = {p.id: p for p in PRESETS}


@dataclass(frozen=True)
class Feed:
    url: str
    name: str
    badge: str


def enabled_feeds(news_cfg: dict) -> list[Feed]:
    feeds: list[Feed] = []
    for pid in news_cfg.get("feeds", []):
        if p := PRESETS_BY_ID.get(pid):
            feeds.append(Feed(p.url, p.name, p.badge))
    for custom in news_cfg.get("custom", []):
        if custom.get("enabled", True) and custom.get("url"):
            name = sanitize(custom.get("name") or custom["url"])
            feeds.append(Feed(custom["url"], name, sanitize(custom.get("badge") or name)[:10]))
    seen: set[str] = set()
    return [f for f in feeds if not (f.url in seen or seen.add(f.url))]


# -- parsing -------------------------------------------------------------------------

@dataclass
class Item:
    title: str
    link: str
    published: float | None
    image: str | None = None


_TAG = re.compile(r"<[^>]+>")
_XML_DECL = re.compile(rb"^\s*<\?xml[^>]*\?>")
_NAMED_ENTITY = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")
_XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child(el, *names: str):
    for name in names:
        for c in el:
            if _local(c.tag) == name:
                return c
    return None


def _clean(text: str) -> str:
    # Titles are often HTML-escaped twice or carry markup inside CDATA.
    return sanitize(html.unescape(_TAG.sub("", html.unescape(text))))


def parse_date(value: str | None) -> float | None:
    from email.utils import parsedate_to_datetime

    if not value or not value.strip():
        return None
    value = value.strip()
    dt = None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _fix_entities(data: bytes) -> bytes:
    """Replace HTML-only named entities (&nbsp; &rsquo; ...) that XML rejects."""
    text = _XML_DECL.sub(b"", data).decode("utf-8", "replace")

    def repl(m: re.Match) -> str:
        if m.group(1) in _XML_ENTITIES:
            return m.group(0)
        ch = html.unescape(m.group(0))
        return f"&#{ord(ch)};" if len(ch) == 1 else "&amp;" + m.group(0)[1:]

    return _NAMED_ENTITY.sub(repl, text).encode("utf-8")


def parse_feed(data: bytes) -> tuple[str, list[Item]]:
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        root = ET.fromstring(_fix_entities(data))

    feed_title = ""
    for el in root.iter():
        if _local(el.tag) in ("channel", "feed"):
            t = _child(el, "title")
            if t is not None:
                feed_title = _clean("".join(t.itertext()))
            break
    if not feed_title and _local(root.tag) == "feed":
        t = _child(root, "title")
        feed_title = _clean("".join(t.itertext())) if t is not None else ""

    items: list[Item] = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        t = _child(el, "title")
        title = _clean("".join(t.itertext())) if t is not None else ""
        if not title:
            continue
        link = ""
        for c in el:
            if _local(c.tag) != "link":
                continue
            href = c.get("href")
            if href and c.get("rel", "alternate") == "alternate":
                link = href
                break
            if href and not link:
                link = href
            elif c.text and c.text.strip() and not link:
                link = c.text.strip()
        if not link:
            guid = _child(el, "guid", "id")
            if guid is not None and (guid.text or "").strip().startswith("http"):
                link = guid.text.strip()
        d = _child(el, "pubDate", "published", "updated", "date", "issued")
        items.append(Item(title, link, parse_date(d.text if d is not None else None), _item_image(el)))
    return feed_title, items


MEDIA_NS = "{http://search.yahoo.com/mrss/}"
_IMG_SRC = re.compile(r"""<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", re.I)


def _item_image(el) -> str | None:
    """The best picture an item offers: media:content / media:thumbnail (largest),
    an image enclosure, or the first <img> in its HTML."""
    best, best_w = None, -1
    for node in el.iter():
        tag = node.tag if isinstance(node.tag, str) else ""
        url = node.get("url") or node.get("href")
        if not url:
            continue
        kind = (node.get("type") or "").lower()
        medium = (node.get("medium") or "").lower()
        is_media = tag in (MEDIA_NS + "content", MEDIA_NS + "thumbnail")
        is_enclosure = _local(tag) == "enclosure" or (_local(tag) == "link" and node.get("rel") == "enclosure")
        if not (is_media or is_enclosure):
            continue
        if kind and not kind.startswith("image/") and medium != "image":
            continue
        if not kind and medium not in ("", "image") and not tag.endswith("thumbnail"):
            continue
        try:
            w = int(node.get("width") or 0)
        except ValueError:
            w = 0
        if w > best_w:
            best, best_w = url, w
    if best:
        return html.unescape(best)
    for name in ("encoded", "description", "content", "summary"):
        node = _child(el, name)
        if node is not None and node.text and (m := _IMG_SRC.search(html.unescape(node.text))):
            return html.unescape(m.group(1))
    return None


def fetch_feed(url: str) -> tuple[str, list[Item]]:
    from . import net

    return parse_feed(net.get(url, timeout=12, max_bytes=5_000_000))


# -- choosing what to show ---------------------------------------------------------------

@dataclass
class Headline:
    badge: str
    source: str
    title: str
    link: str
    published: float | None
    image: str | None = None


def select_headlines(rows, feeds: list[Feed], *, count: int, per_source: int,
                     max_age_hours: float, now: float | None = None) -> list[Headline]:
    """Interleave the freshest items from each feed, so no single source dominates."""
    now = now or time.time()
    cutoff = now - max_age_hours * 3600 if max_age_hours and max_age_hours > 0 else None
    by_url = {f.url: f for f in feeds}
    per_feed: dict[str, list] = {}
    for row in rows:
        when = row["published"] or row["fetched_at"]
        if cutoff and when and when < cutoff:
            continue
        per_feed.setdefault(row["feed"], []).append((when or 0, row))
    for items in per_feed.values():
        items.sort(key=lambda x: x[0], reverse=True)
    order = sorted(per_feed, key=lambda url: per_feed[url][0][0], reverse=True)

    out: list[Headline] = []
    seen_titles: set[str] = set()
    for _ in range(max(per_source, 1)):  # each round takes at most one item per feed
        for url in order:
            if len(out) >= count:
                return out
            feed = by_url.get(url, Feed(url, url, url[:10]))
            items = per_feed[url]
            while items:
                _, row = items.pop(0)
                key = row["title"].casefold()
                if key in seen_titles:
                    continue
                seen_titles.add(key)
                out.append(Headline(feed.badge, feed.name, row["title"], row["link"], row["published"],
                                    row["image"] if "image" in row.keys() else None))
                break
    return out
