"""Reads Christopher Johnson's ASCII Art Collection (https://asciiart.website).

Only the public HTML pages are used: browse.php for the category catalog and
cat.php for art.  cat.php serves a random 20 pieces of a category per request,
so repeated low-volume fetches gradually fill the local cache.
"""

from __future__ import annotations

import html
import re

from .store import Art
from .textutil import cell_width, sanitize, sanitize_block

BASE = "https://asciiart.website"
BROWSE_URL = f"{BASE}/browse.php"


def category_url(category_id: int) -> str:
    return f"{BASE}/cat.php?category_id={category_id}"


def art_url(art_id: int) -> str:
    return f"{BASE}/art/{art_id}"


_TAG = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    return sanitize(html.unescape(_TAG.sub("", fragment)))


# -- catalog (browse.php) -------------------------------------------------------

_GROUPING_SPLIT = re.compile(r'<li class="grouping" data-grouping-id="(\d+)"')
_GROUPING_LABEL = re.compile(
    r'class="grouping-label">\s*(.*?)\s*<span class="category-count">\((\d+)\)', re.S
)
_CATEGORY = re.compile(
    r'href="cat\.php\?category_id=(\d+)"[^>]*>\s*(.*?)\s*<span class="category-count">\((\d+)\)', re.S
)


def parse_catalog(page: str) -> tuple[list[tuple[int, str, int]], list[tuple[int, int, str, int]]]:
    """-> ([(grouping_id, name, count)], [(category_id, grouping_id, name, count)])"""
    groupings, categories = [], []
    parts = _GROUPING_SPLIT.split(page)
    for gid, chunk in zip(parts[1::2], parts[2::2]):
        label = _GROUPING_LABEL.search(chunk)
        if not label:
            continue
        groupings.append((int(gid), _text(label.group(1)), int(label.group(2))))
        for m in _CATEGORY.finditer(chunk):
            categories.append((int(m.group(1)), int(gid), _text(m.group(2)), int(m.group(3))))
    return groupings, categories


# -- artworks (cat.php) -----------------------------------------------------------

_ART_SPLIT = re.compile(r'<div class="adu-artwork-display"')
_ART_END = "<!-- .adu-artwork-display -->"
_ART_ID = re.compile(r'\bid="artwork-(\d+)"')
_FLAG = re.compile(r'data-(?:nudity|explicit)="(\d+)"')
_TITLE = re.compile(r"<h3>\s*<a\b[^>]*>(.*?)</a>", re.S)
_PRE = re.compile(r"<pre\b[^>]*>(.*?)</pre>", re.S)
_FIELD = re.compile(r"<strong>(Categories|Tags|Artist):</strong>(.*?)</p>", re.S)
_CATEGORY_LINK = re.compile(r'category_id=(\d+)"[^>]*>(.*?)</a>', re.S)
_TAG_LINK = re.compile(r'tag_id=\d+"[^>]*>(.*?)</a>', re.S)


def clean_art(raw: str) -> str:
    """Normalise art text: expand tabs, drop control characters, trailing
    whitespace, blank edge lines and any indentation common to every line."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    lines = [sanitize_block(line.expandtabs(8)).rstrip() for line in text.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""
    indent = min(len(line) - len(line.lstrip(" ")) for line in lines if line.strip())
    return "\n".join(line[indent:] for line in lines)


def parse_artworks(page: str) -> list[Art]:
    pieces = []
    for chunk in _ART_SPLIT.split(page)[1:]:
        end = chunk.find(_ART_END)
        if end != -1:
            chunk = chunk[:end]
        opening = chunk[: chunk.find(">")]
        art_id = _ART_ID.search(opening)
        pre = _PRE.search(chunk)
        if not art_id or not pre:
            continue
        text = clean_art(html.unescape(_TAG.sub("", pre.group(1))))
        if not text:
            continue
        lines = text.split("\n")
        title = _TITLE.search(chunk)
        fields = {name: body for name, body in _FIELD.findall(chunk)}
        pieces.append(
            Art(
                id=int(art_id.group(1)),
                title=_text(title.group(1)) if title else "",
                artist=_text(fields.get("Artist", "")),
                width=max(cell_width(line) for line in lines),
                height=len(lines),
                flagged=any(int(v) for v in _FLAG.findall(opening)),
                text=text,
                categories=[(int(cid), _text(name)) for cid, name in _CATEGORY_LINK.findall(fields.get("Categories", ""))],
                tags=[_text(t) for t in _TAG_LINK.findall(fields.get("Tags", ""))],
            )
        )
    return pieces


def fetch_catalog():
    from . import net

    return parse_catalog(net.get(BROWSE_URL, timeout=30).decode("utf-8", "replace"))


def fetch_category(category_id: int) -> list[Art]:
    from . import net

    return parse_artworks(net.get(category_url(category_id), timeout=20).decode("utf-8", "replace"))
