"""Terminal text helpers: display width, ANSI stripping, sanitising untrusted text."""

from __future__ import annotations

import re
import unicodedata

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
# C0 controls except \t and \n, DEL, and C1 controls.  ESC is in here, so text
# scraped from the web or an RSS feed can never inject terminal sequences.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_SPACES = re.compile(r"\s+")


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def sanitize(text: str) -> str:
    """Single-line, control-free text (for titles and headlines)."""
    return _SPACES.sub(" ", _CONTROL.sub("", text.replace("\t", " ").replace("\n", " "))).strip()


def sanitize_block(text: str) -> str:
    """Multi-line text with control characters (other than newlines) removed."""
    return _CONTROL.sub("", text)


def char_width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def cell_width(text: str) -> int:
    if text.isascii():
        return len(text)
    return sum(char_width(ch) for ch in text)


def visible_width(text: str) -> int:
    return cell_width(strip_ansi(text))


def truncate(text: str, width: int, ellipsis: str = "…") -> str:
    """Cut plain text to at most `width` cells, marking the cut with `ellipsis`."""
    if width <= 0:
        return ""
    if cell_width(text) <= width:
        return text
    room = width - cell_width(ellipsis)
    if room <= 0:
        return ellipsis[:width]
    out, used = [], 0
    for ch in text:
        w = char_width(ch)
        if used + w > room:
            break
        out.append(ch)
        used += w
    return "".join(out).rstrip() + ellipsis


def slice_cells(text: str, start: int, width: int) -> str:
    """The part of `text` covering cells [start, start + width)."""
    if text.isascii():
        return text[start : start + width]
    out, pos = [], 0
    for ch in text:
        w = char_width(ch)
        if pos >= start and pos + w <= start + width:
            out.append(ch)
        pos += w
        if pos >= start + width:
            break
    return "".join(out)
