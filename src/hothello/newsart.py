"""ASCII art made from the picture of the top news story.

The background refresh downloads the image and shrinks it to a small RGB grid
(that part needs Pillow).  At login the grid is resampled to the space the art
gets and turned into characters - standard library only, a few milliseconds.
"""

from __future__ import annotations

import bisect
import html
import io
import re
import zlib
from urllib.parse import urljoin, urlsplit

from .store import Art

STYLES = {
    "ascii": "ASCII characters chosen by brightness",
    "blocks": "Half-block pixels (closest to the photo)",
}
COLORS = {
    "image": "The picture's own colours",
    "theme": "Your theme's art colours",
    "mono": "No colour",
}
# Darkest to brightest.  A short ramp reads as classic ASCII art; long ones look noisy.
RAMP = " .:-=+*#%@"
EQUALIZE = 0.5  # blend of plain brightness and rank (histogram-equalised) brightness
MAX_SIDE = 160  # pixels kept per picture: plenty for a terminal, small in the cache


# -- finding a picture (refresh time) -------------------------------------------------------

_META = re.compile(r"<meta\b[^>]*>", re.I)
_PROP = re.compile(r"""(?:property|name)\s*=\s*["'](og:image(?::secure_url)?|twitter:image(?::src)?)["']""", re.I)
_CONTENT = re.compile(r"""content\s*=\s*["']([^"']+)["']""", re.I)


def page_image(page: str, base_url: str) -> str | None:
    """The og:image / twitter:image an article page advertises for link previews."""
    for tag in _META.findall(page):
        if _PROP.search(tag) and (m := _CONTENT.search(tag)):
            url = urljoin(base_url, html.unescape(m.group(1).strip()))
            if url.lower().startswith(("http://", "https://")):
                return url
    return None


def prepare(data: bytes, max_side: int = MAX_SIDE) -> tuple[int, int, bytes]:
    """Decode an image into a small, contrast-stretched RGB grid -> (w, h, zlib bytes)."""
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = 40_000_000  # refuse decompression bombs
    with Image.open(io.BytesIO(data)) as im:
        im.draft("RGB", (max_side * 2, max_side * 2))  # fast JPEG downscale while decoding
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        im = ImageOps.autocontrast(im, cutoff=1)
        return im.width, im.height, zlib.compress(im.tobytes(), 6)


# -- turning it into text (login time, stdlib only) -----------------------------------------------

RGB = tuple[int, int, int]


def fit(pw: int, ph: int, max_w: int, max_h: int | None, cap_w: int = 0) -> tuple[int, int]:
    """Columns x rows for a pw x ph picture; a cell is about twice as tall as wide."""
    w = min(max_w, cap_w) if cap_w else max_w
    h = max(1, round(w * ph / pw / 2))
    if max_h is not None and h > max_h:
        h = max_h
        w = min(w, max(1, round(h * 2 * pw / ph)))
    return max(w, 1), h


def grid(pixels: bytes, pw: int, ph: int, tw: int, th: int) -> list[list[RGB]]:
    """Box-average the picture down to tw x th colours."""
    xs = []
    for x in range(tw):
        x0 = x * pw // tw
        xs.append((x0, max(x0 + 1, (x + 1) * pw // tw)))
    out = []
    for y in range(th):
        y0 = y * ph // th
        y1 = max(y0 + 1, (y + 1) * ph // th)
        row = []
        for x0, x1 in xs:
            r = g = b = 0
            for yy in range(y0, y1):
                start = (yy * pw + x0) * 3
                chunk = pixels[start:start + (x1 - x0) * 3]
                r += sum(chunk[0::3])
                g += sum(chunk[1::3])
                b += sum(chunk[2::3])
            n = (y1 - y0) * (x1 - x0)
            row.append((r // n, g // n, b // n))
        out.append(row)
    return out


def render(pixels: bytes, pw: int, ph: int, *, max_w: int, max_h: int | None, cap_w: int = 0,
           style: str = "ascii", light_background: bool = False):
    """-> (lines, fg colours, bg colours or None), each rows x cols."""
    w, h = fit(pw, ph, max_w, max_h, cap_w)
    if style == "blocks":
        cells = grid(pixels, pw, ph, w, h * 2)
        fg = [cells[2 * y] for y in range(h)]
        bg = [cells[2 * y + 1] for y in range(h)]
        return ["▀" * w] * h, fg, bg
    cells = grid(pixels, pw, ph, w, h)
    lum = [[(0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 for r, g, b in row] for row in cells]
    ranked = sorted(v for row in lum for v in row)
    last = max(len(ranked) - 1, 1)
    top = len(RAMP) - 1
    lines = []
    for row in lum:
        chars = []
        for v in row:
            # Mixing in each cell's rank spreads the characters over the whole ramp, so a
            # bright sky or a dark room still shows its shapes.
            t = (1 - EQUALIZE) * v + EQUALIZE * bisect.bisect_left(ranked, v) / last
            if light_background:
                t = 1 - t
            chars.append(RAMP[round(t * top)])
        lines.append("".join(chars).rstrip() or " ")
    return lines, cells, None


def domain(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


def picture_art(store, headlines, art_cfg: dict, *, max_w: int, max_h: int | None,
                light_background: bool = False) -> Art | None:
    """The top headline that has a cached picture, as a piece of art."""
    for h in headlines:
        row = store.get_picture(h.link)
        if row is None or row["pixels"] is None:
            continue
        if max_h is not None and max_h < 3:
            return None
        pixels = zlib.decompress(row["pixels"])
        lines, fg, bg = render(
            pixels, row["width"], row["height"], max_w=max_w, max_h=max_h,
            cap_w=int(art_cfg.get("picture_width", 64) or 0),
            style=art_cfg.get("picture_style", "ascii"), light_background=light_background,
        )
        width = max(len(line) for line in lines)
        return Art(id=0, title=h.title, artist=h.source, width=width, height=len(lines), flagged=False,
                   text="\n".join(lines), url=h.link, fg=fg, bg=bg)
    return None
