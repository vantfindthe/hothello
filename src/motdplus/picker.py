"""Choosing which cached piece of art to show."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from .store import Art, ArtFilter, Store


@dataclass
class Pick:
    art: Art | None
    lines: list[str]  # the art's lines, cropped when it had to be
    cropped: bool = False
    pool_left: int = 0  # unseen pieces that still fit, after this pick


def _same_period(then: float, now: float, change: str) -> bool:
    a, b = time.localtime(then), time.localtime(now)
    if change == "daily":
        return (a.tm_year, a.tm_yday) == (b.tm_year, b.tm_yday)
    if change == "hourly":
        return (a.tm_year, a.tm_yday, a.tm_hour) == (b.tm_year, b.tm_yday, b.tm_hour)
    return False


def crop(lines: list[str], width: int, height: int | None) -> list[str]:
    """Centre-crop a block of text to width x height."""
    from .textutil import cell_width, slice_cells

    if height is not None and len(lines) > height:
        top = (len(lines) - height) // 2
        lines = lines[top : top + height]
    block_w = max((cell_width(line) for line in lines), default=0)
    if block_w > width:
        left = (block_w - width) // 2
        lines = [slice_cells(line, left, width).rstrip() for line in lines]
    return lines


def _rotate(store: Store, flt: ArtFilter, categories: list[int], dry_run: bool, large: bool) -> Art | None:
    """Next category (after the last one used) that still has unseen fitting art."""
    available = store.categories_with_art(flt, unseen=True)
    unseen = True
    if not available:
        if dry_run:
            unseen = False  # a preview must not reset the history
        else:
            store.reset_shown(flt)
        available = store.categories_with_art(flt, unseen=unseen)
    order = categories or sorted(available)
    if not order:
        return None
    last = store.kv_get("rotate_last")
    start = order.index(last) + 1 if last in order else 0
    for i in range(len(order)):
        cid = order[(start + i) % len(order)]
        if cid in available and (art := store.random_art(flt, unseen=unseen, category=cid, prefer_large=large)):
            if not dry_run:
                store.kv_set("rotate_last", cid)
            return art
    return None


def pick(store: Store, art_cfg: dict, display: dict, *, max_width: int, max_height: int | None,
         now: float | None = None, dry_run: bool = False, prefer_id: int | None = None) -> Pick:
    now = now or time.time()
    min_h = max(int(display.get("min_height", 1)), 1)
    min_w = max(int(display.get("min_width", 1)), 1)
    flt = ArtFilter(
        categories=list(art_cfg.get("categories") or []) or None,
        min_width=min(min_w, max_width), max_width=max_width,
        min_height=min_h, max_height=max_height,
        hide_flagged=bool(art_cfg.get("hide_flagged", True)),
    )
    if max_height is not None and max_height < min(min_h, 3):
        return Pick(None, [])  # no room worth drawing in

    def done(art: Art, *, cropped: bool = False, record: bool = True) -> Pick:
        lines = crop(art.lines, max_width, max_height) if cropped else art.lines
        if record and not dry_run:
            store.mark_shown(art.id, now)
            store.kv_set("current", {"id": art.id, "at": now})
        return Pick(art, lines, cropped, store.count(flt, unseen=True))

    if prefer_id is not None and (art := store.get_art(prefer_id)) and flt.fits(art):
        return done(art, record=False)

    change = art_cfg.get("change", "login")
    if change != "login":
        current = store.kv_get("current")
        if current and _same_period(current["at"], now, change):
            art = store.get_art(current["id"])
            if art and flt.fits(art):
                return done(art, record=False)

    cycle = art_cfg.get("cycle", "shuffle")
    large = art_cfg.get("prefer", "any") == "large"
    art = None
    if cycle == "random":
        art = store.random_art(flt, prefer_large=large)
    elif cycle == "rotate":
        art = _rotate(store, flt, list(art_cfg.get("categories") or []), dry_run, large)
    else:
        art = store.random_art(flt, unseen=True, prefer_large=large)
        if art is None and store.count(flt):
            if dry_run:
                art = store.random_art(flt, prefer_large=large)
            else:
                store.reset_shown(flt)  # every fitting piece has been shown: start a new round
                art = store.random_art(flt, unseen=True, prefer_large=large)
    if art is not None:
        return done(art)

    if display.get("oversize", "crop") == "crop":
        loose = ArtFilter(flt.categories, 1, None, min_h, None, flt.hide_flagged)
        candidates = store.least_oversized(loose, max_width, max_height or 10**6)
        if candidates:
            return done(random.choice(candidates), cropped=True)
    return Pick(None, [])
