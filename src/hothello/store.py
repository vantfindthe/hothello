"""SQLite cache: the category catalog, fetched art, show history and headlines."""

from __future__ import annotations

import json
import random
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS groupings (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, count INTEGER
);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY, grouping_id INTEGER, name TEXT NOT NULL,
    count INTEGER, fetched_at REAL
);
CREATE TABLE IF NOT EXISTS category_groupings (
    category_id INTEGER, grouping_id INTEGER, PRIMARY KEY (category_id, grouping_id)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS art (
    id INTEGER PRIMARY KEY, title TEXT, artist TEXT, width INTEGER, height INTEGER,
    flagged INTEGER DEFAULT 0, text TEXT NOT NULL, tags TEXT, added_at REAL
);
CREATE INDEX IF NOT EXISTS ix_art_size ON art(height, width);
CREATE TABLE IF NOT EXISTS art_categories (
    art_id INTEGER, category_id INTEGER, PRIMARY KEY (art_id, category_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_art_categories_cat ON art_categories(category_id);
CREATE TABLE IF NOT EXISTS shown (art_id INTEGER PRIMARY KEY, shown_at REAL);
CREATE TABLE IF NOT EXISTS headlines (
    feed TEXT, title TEXT, link TEXT, published REAL, fetched_at REAL,
    PRIMARY KEY (feed, link)
);
CREATE TABLE IF NOT EXISTS pictures (
    link TEXT PRIMARY KEY, image_url TEXT, width INTEGER, height INTEGER, pixels BLOB,
    error TEXT, fetched_at REAL
);
CREATE TABLE IF NOT EXISTS feed_status (
    feed TEXT PRIMARY KEY, title TEXT, fetched_at REAL, ok INTEGER, error TEXT, items INTEGER
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""


@dataclass
class Art:
    id: int
    title: str
    artist: str
    width: int
    height: int
    flagged: bool
    text: str
    categories: list[tuple[int, str]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    url: str | None = None  # credit link, when it isn't an asciiart.website piece
    fg: list | None = None  # per-cell colours (news pictures)
    bg: list | None = None

    @property
    def lines(self) -> list[str]:
        return self.text.split("\n")


@dataclass
class ArtFilter:
    """Which cached art may be shown.  None means "no limit"."""

    categories: list[int] | None = None
    min_width: int = 1
    max_width: int | None = None
    min_height: int = 1
    max_height: int | None = None
    hide_flagged: bool = True

    def where(self, alias: str = "a") -> tuple[str, list]:
        clauses = [f"{alias}.width >= ?", f"{alias}.height >= ?"]
        params: list = [self.min_width, self.min_height]
        if self.max_width is not None:
            clauses.append(f"{alias}.width <= ?")
            params.append(self.max_width)
        if self.max_height is not None:
            clauses.append(f"{alias}.height <= ?")
            params.append(self.max_height)
        if self.hide_flagged:
            clauses.append(f"{alias}.flagged = 0")
        if self.categories:
            marks = ",".join("?" * len(self.categories))
            clauses.append(
                f"{alias}.id IN (SELECT art_id FROM art_categories WHERE category_id IN ({marks}))"
            )
            params.extend(self.categories)
        return " AND ".join(clauses), params

    def fits(self, art: Art) -> bool:
        return (
            art.width >= self.min_width
            and art.height >= self.min_height
            and (self.max_width is None or art.width <= self.max_width)
            and (self.max_height is None or art.height <= self.max_height)
            and not (self.hide_flagged and art.flagged)
            and (not self.categories or any(c in self.categories for c, _ in art.categories))
        )


class Store:
    def __init__(self, path: Path | str | None = None):
        path = Path(path or paths.db_file())
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        # Caches made by older versions lack newer columns.
        if "image" not in {r[1] for r in self.db.execute("PRAGMA table_info(headlines)")}:
            with self.db:
                self.db.execute("ALTER TABLE headlines ADD COLUMN image TEXT")

    def close(self) -> None:
        self.db.close()

    # -- key/value state ---------------------------------------------------

    def kv_get(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def kv_set(self, key: str, value) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, json.dumps(value))
            )

    # -- catalog -------------------------------------------------------------

    def replace_catalog(self, groupings: list[tuple[int, str, int]], categories: list[tuple[int, int, str, int]]) -> None:
        """Categories may be listed under several groupings; the first one is their home."""
        with self.db:
            self.db.execute("DELETE FROM groupings")
            self.db.execute("DELETE FROM category_groupings")
            self.db.executemany("INSERT INTO groupings (id, name, count) VALUES (?, ?, ?)", groupings)
            self.db.executemany(
                "INSERT OR IGNORE INTO category_groupings (category_id, grouping_id) VALUES (?, ?)",
                [(cid, gid) for cid, gid, _, _ in categories],
            )
            seen: set[int] = set()
            for cid, gid, name, count in categories:
                if cid in seen:
                    continue
                seen.add(cid)
                self.db.execute(
                    """INSERT INTO categories (id, grouping_id, name, count) VALUES (?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET grouping_id = excluded.grouping_id,
                       name = excluded.name, count = excluded.count""",
                    (cid, gid, name, count),
                )
            self.db.execute(
                "INSERT OR REPLACE INTO kv (key, value) VALUES ('catalog_at', ?)", (json.dumps(time.time()),)
            )

    def groupings(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT id, name, count FROM groupings ORDER BY name").fetchall()

    def categories(self) -> list[sqlite3.Row]:
        """Every known category with how many of its pieces are cached."""
        return self.db.execute(
            """SELECT c.id, c.grouping_id, c.name, c.count, c.fetched_at,
                      (SELECT COUNT(*) FROM art_categories ac WHERE ac.category_id = c.id) AS cached
               FROM categories c ORDER BY c.name"""
        ).fetchall()

    def category_groupings(self) -> list[tuple[int, int]]:
        """(category_id, grouping_id) for every place a category is listed."""
        return [(r[0], r[1]) for r in self.db.execute("SELECT category_id, grouping_id FROM category_groupings")]

    def category_names(self) -> dict[int, str]:
        return {r[0]: r[1] for r in self.db.execute("SELECT id, name FROM categories")}

    def mark_category_fetched(self, category_id: int, when: float) -> None:
        with self.db:
            self.db.execute("UPDATE categories SET fetched_at = ? WHERE id = ?", (when, category_id))

    # -- art -------------------------------------------------------------------

    def upsert_art(self, pieces: list[Art]) -> int:
        """Store pieces; returns how many were new."""
        now = time.time()
        new = 0
        with self.db:
            for art in pieces:
                new += self.db.execute("SELECT 1 FROM art WHERE id = ?", (art.id,)).fetchone() is None
                self.db.execute(
                    """INSERT INTO art (id, title, artist, width, height, flagged, text, tags, added_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET title = excluded.title, artist = excluded.artist,
                       width = excluded.width, height = excluded.height, flagged = excluded.flagged,
                       text = excluded.text, tags = excluded.tags""",
                    (art.id, art.title, art.artist, art.width, art.height, int(art.flagged),
                     art.text, json.dumps(art.tags), now),
                )
                for cid, name in art.categories:
                    self.db.execute(
                        "INSERT OR IGNORE INTO art_categories (art_id, category_id) VALUES (?, ?)", (art.id, cid)
                    )
                    self.db.execute("INSERT OR IGNORE INTO categories (id, name) VALUES (?, ?)", (cid, name))
        return new

    def _art_from_row(self, row: sqlite3.Row) -> Art:
        cats = self.db.execute(
            """SELECT c.id, c.name FROM art_categories ac JOIN categories c ON c.id = ac.category_id
               WHERE ac.art_id = ? ORDER BY c.name""",
            (row["id"],),
        ).fetchall()
        return Art(
            id=row["id"], title=row["title"] or "", artist=row["artist"] or "",
            width=row["width"], height=row["height"], flagged=bool(row["flagged"]),
            text=row["text"], categories=[(c[0], c[1]) for c in cats],
            tags=json.loads(row["tags"] or "[]"),
        )

    def get_art(self, art_id: int) -> Art | None:
        row = self.db.execute("SELECT * FROM art WHERE id = ?", (art_id,)).fetchone()
        return self._art_from_row(row) if row else None

    def art_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM art").fetchone()[0]

    def count(self, flt: ArtFilter, *, unseen: bool = False) -> int:
        where, params = flt.where()
        if unseen:
            where += " AND a.id NOT IN (SELECT art_id FROM shown)"
        return self.db.execute(f"SELECT COUNT(*) FROM art a WHERE {where}", params).fetchone()[0]

    def random_art(self, flt: ArtFilter, *, unseen: bool = False, category: int | None = None,
                   prefer_large: bool = False) -> Art | None:
        where, params = flt.where()
        if unseen:
            where += " AND a.id NOT IN (SELECT art_id FROM shown)"
        if category is not None:
            where += " AND a.id IN (SELECT art_id FROM art_categories WHERE category_id = ?)"
            params.append(category)
        if prefer_large:  # weighted by area, so big pieces come up far more often
            rows = self.db.execute(f"SELECT a.id, a.width * a.height FROM art a WHERE {where}", params).fetchall()
            if not rows:
                return None
            art_id = random.choices([r[0] for r in rows], weights=[r[1] for r in rows])[0]
            return self.get_art(art_id)
        row = self.db.execute(
            f"SELECT * FROM art a WHERE {where} ORDER BY random() LIMIT 1", params
        ).fetchone()
        return self._art_from_row(row) if row else None

    def categories_with_art(self, flt: ArtFilter, *, unseen: bool = False) -> set[int]:
        where, params = flt.where()
        if unseen:
            where += " AND a.id NOT IN (SELECT art_id FROM shown)"
        rows = self.db.execute(
            f"""SELECT DISTINCT ac.category_id FROM art a
                JOIN art_categories ac ON ac.art_id = a.id WHERE {where}""",
            params,
        ).fetchall()
        return {r[0] for r in rows}

    def least_oversized(self, flt: ArtFilter, width: int, height: int, limit: int = 12) -> list[Art]:
        """Pieces that would need the least cropping to fit width x height."""
        where, params = flt.where()
        rows = self.db.execute(
            f"""SELECT *, MAX(a.width * 1.0 / ?, a.height * 1.0 / ?) AS over FROM art a
                WHERE {where} ORDER BY over ASC, random() LIMIT ?""",
            [max(width, 1), max(height, 1), *params, limit],
        ).fetchall()
        return [self._art_from_row(r) for r in rows]

    def mark_shown(self, art_id: int, when: float) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO shown (art_id, shown_at) VALUES (?, ?)", (art_id, when))

    def reset_shown(self, flt: ArtFilter) -> None:
        where, params = flt.where()
        with self.db:
            self.db.execute(f"DELETE FROM shown WHERE art_id IN (SELECT a.id FROM art a WHERE {where})", params)

    # -- headlines ---------------------------------------------------------------

    def replace_headlines(self, feed: str, items: list[tuple], when: float) -> None:
        """items: (title, link, published) or (title, link, published, image url)."""
        with self.db:
            self.db.execute("DELETE FROM headlines WHERE feed = ?", (feed,))
            self.db.executemany(
                """INSERT OR IGNORE INTO headlines (feed, title, link, published, fetched_at, image)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [(feed, it[0], it[1], it[2], when, it[3] if len(it) > 3 else None) for it in items],
            )

    def headlines(self, feeds: list[str]) -> list[sqlite3.Row]:
        if not feeds:
            return []
        marks = ",".join("?" * len(feeds))
        return self.db.execute(
            f"SELECT feed, title, link, published, fetched_at, image FROM headlines WHERE feed IN ({marks})",
            feeds,
        ).fetchall()

    # -- news pictures -----------------------------------------------------------------------

    def get_picture(self, link: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM pictures WHERE link = ?", (link,)).fetchone()

    def put_picture(self, link: str, *, image_url: str | None, width: int = 0, height: int = 0,
                    pixels: bytes | None = None, error: str | None = None, when: float) -> None:
        with self.db:
            self.db.execute(
                """INSERT OR REPLACE INTO pictures (link, image_url, width, height, pixels, error, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (link, image_url, width, height, pixels, error, when),
            )

    def prune_pictures(self, keep: set[str], older_than: float) -> None:
        with self.db:
            rows = self.db.execute("SELECT link FROM pictures WHERE fetched_at < ?", (older_than,)).fetchall()
            self.db.executemany("DELETE FROM pictures WHERE link = ?", [(r[0],) for r in rows if r[0] not in keep])

    def set_feed_status(self, feed: str, *, title: str | None, ok: bool, error: str | None, items: int, when: float) -> None:
        with self.db:
            self.db.execute(
                """INSERT OR REPLACE INTO feed_status (feed, title, fetched_at, ok, error, items)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (feed, title, when, int(ok), error, items),
            )

    def feed_status(self) -> dict[str, sqlite3.Row]:
        return {r["feed"]: r for r in self.db.execute("SELECT * FROM feed_status")}
