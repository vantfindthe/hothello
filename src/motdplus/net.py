"""Tiny HTTP GET with a size cap and bounded decompression (stdlib only)."""

from __future__ import annotations

import urllib.error
import urllib.request
import zlib

from . import __version__

USER_AGENT = f"motdplus/{__version__} (terminal greeting; low-volume personal use)"


class FetchError(Exception):
    pass


def _inflate(data: bytes, wbits: int, max_bytes: int) -> bytes:
    d = zlib.decompressobj(wbits)
    out = d.decompress(data, max_bytes + 1)
    if len(out) > max_bytes or d.unconsumed_tail:
        raise FetchError("response too large")
    return out


def get(url: str, *, timeout: float = 15.0, max_bytes: int = 8_000_000) -> bytes:
    if not url.lower().startswith(("http://", "https://")):
        raise FetchError("only http:// and https:// URLs are supported")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate", "Accept": "*/*"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(max_bytes + 1)
            encoding = (resp.headers.get("Content-Encoding") or "").lower()
    except urllib.error.HTTPError as e:
        raise FetchError(f"HTTP {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise FetchError(str(getattr(e, "reason", e))) from e
    if len(data) > max_bytes:
        raise FetchError("response too large")
    try:
        if encoding == "gzip":
            data = _inflate(data, 16 + zlib.MAX_WBITS, max_bytes)
        elif encoding == "deflate":
            try:
                data = _inflate(data, zlib.MAX_WBITS, max_bytes)
            except zlib.error:
                data = _inflate(data, -zlib.MAX_WBITS, max_bytes)
    except zlib.error as e:
        raise FetchError(f"bad {encoding} data") from e
    return data
