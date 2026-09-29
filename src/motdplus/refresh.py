"""Fetching new art and headlines, normally in a detached background process so
logging in never waits on the network."""

from __future__ import annotations

import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import paths
from .store import Store

CATALOG_MAX_AGE = 30 * 86400
MIN_ART_INTERVAL = 15 * 60  # never hit the art site more often than this unless asked
LOW_WATER = 8  # refresh early when fewer unseen fitting pieces remain
POLITE_DELAY = 1.5  # seconds between page requests to asciiart.website


def catalog_due(store: Store, now: float) -> bool:
    return not store.groupings() or now - (store.kv_get("catalog_at") or 0) > CATALOG_MAX_AGE


def art_due(cfg: dict, store: Store, now: float, pool_left: int | None = None) -> bool:
    art = cfg["art"]
    if not art.get("enabled", True):
        return False
    last = store.kv_get("last_art_refresh") or 0
    if now - last < MIN_ART_INTERVAL:
        return False
    if store.art_count() == 0 or now - last > float(art.get("refresh_hours", 12)) * 3600:
        return True
    if pool_left is not None and pool_left < LOW_WATER:
        return True
    selected = art.get("categories") or []
    if selected:
        fetched = {r["id"] for r in store.categories() if r["fetched_at"]}
        return any(cid not in fetched for cid in selected)
    return False


def news_due(cfg: dict, store: Store, now: float) -> bool:
    news = cfg["news"]
    if not news.get("enabled"):
        return False
    last = store.kv_get("last_news_refresh") or 0
    if now - last > float(news.get("refresh_minutes", 30)) * 60:
        return True
    from .feeds import enabled_feeds

    status = store.feed_status()
    return any(f.url not in status for f in enabled_feeds(news))


def refresh_catalog(store: Store, log=print) -> None:
    from .scraper import fetch_catalog

    groupings, categories = fetch_catalog()
    if not categories:
        raise RuntimeError("could not read the category list from asciiart.website")
    store.replace_catalog(groupings, categories)
    log(f"catalog: {len(groupings)} groups, {len(categories)} categories")


def _choose_categories(cfg: dict, store: Store, k: int) -> list[tuple[int, str]]:
    rows = {r["id"]: r for r in store.categories()}
    selected = cfg["art"].get("categories") or list(rows)
    pool = []
    for cid in selected:
        row = rows.get(cid)
        if row is None:
            pool.append((cid, str(cid), 3.0))
            continue
        missing = max((row["count"] or 0) - row["cached"], 0)
        if missing == 0 and row["fetched_at"]:
            continue  # fully cached already
        weight = (missing + 1) * (3.0 if not row["fetched_at"] else 1.0)
        pool.append((cid, row["name"], weight))
    chosen = []
    while pool and len(chosen) < k:
        i = random.choices(range(len(pool)), weights=[w for _, _, w in pool])[0]
        cid, name, _ = pool.pop(i)
        chosen.append((cid, name))
    return chosen


def refresh_art(cfg: dict, store: Store, log=print, pages: int | None = None) -> int:
    from .scraper import fetch_category

    pages = pages or int(cfg["art"].get("pages_per_refresh", 3))
    new_total = 0
    for i, (cid, name) in enumerate(_choose_categories(cfg, store, pages)):
        if i:
            time.sleep(POLITE_DELAY)
        try:
            pieces = fetch_category(cid)
        except Exception as e:
            log(f"art: {name}: {e}")
            continue
        new = store.upsert_art(pieces)
        store.mark_category_fetched(cid, time.time())
        new_total += new
        log(f"art: {name}: {len(pieces)} pieces, {new} new")
    store.kv_set("last_art_refresh", time.time())
    return new_total


def refresh_news(cfg: dict, store: Store, log=print) -> None:
    from .feeds import enabled_feeds, fetch_feed

    feeds = enabled_feeds(cfg["news"])

    def one(feed):
        try:
            return feed, fetch_feed(feed.url), None
        except Exception as e:  # network errors, bad XML, anything: report and move on
            return feed, None, str(e) or e.__class__.__name__

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(one, feeds))
    now = time.time()
    for feed, parsed, error in results:
        if parsed is None:
            store.set_feed_status(feed.url, title=None, ok=False, error=error, items=0, when=now)
            log(f"news: {feed.name}: {error}")
            continue
        title, items = parsed
        store.replace_headlines(feed.url, [(it.title, it.link, it.published) for it in items], now)
        store.set_feed_status(feed.url, title=title, ok=True, error=None, items=len(items), when=now)
        log(f"news: {feed.name}: {len(items)} items")
    store.kv_set("last_news_refresh", now)


def run(cfg: dict, store: Store, *, art: bool = True, news: bool = True, catalog: bool | None = None,
        if_due: bool = False, log=print) -> None:
    now = time.time()
    if catalog is None:
        catalog = art and catalog_due(store, now)
    if catalog:
        try:
            refresh_catalog(store, log)
        except Exception as e:
            log(f"catalog: {e}")
    if art and (not if_due or art_due(cfg, store, now, store.kv_get("pool_left"))):
        refresh_art(cfg, store, log)
    if news and (not if_due or news_due(cfg, store, now)):
        refresh_news(cfg, store, log)


class Lock:
    """Cross-process "someone is already refreshing" marker; stale after 15 minutes."""

    def __init__(self, path: Path | None = None, stale_after: float = 900):
        self.path = path or paths.lock_file()
        self.stale_after = stale_after
        self.held = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self.held = True
                return True
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale_after:
                        self.path.unlink()
                        continue
                except OSError:
                    pass
                return False
        return False

    def release(self) -> None:
        if self.held:
            try:
                self.path.unlink()
            except OSError:
                pass
            self.held = False

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()


def python_for_background() -> str:
    exe = Path(sys.executable)
    if os.name == "nt":
        windowless = exe.with_name("pythonw.exe")
        if windowless.exists():
            return str(windowless)
    return str(exe)


def spawn_background() -> None:
    """Start `motdplus refresh --if-due` fully detached from this terminal."""
    cmd = [python_for_background(), "-m", "motdplus", "refresh", "--if-due", "--quiet"]
    kwargs: dict = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        )
    else:
        kwargs["start_new_session"] = True
    # Make sure the child can import motdplus even when it isn't installed site-wide.
    env = dict(os.environ)
    pkg_root = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = pkg_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    subprocess.Popen(cmd, env=env, **kwargs)
