"""Builds the whole MOTD for a given screen size: picks art, gathers headlines, renders."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from . import picker, render, sysinfo, sysstat, term, themes
from .config import SIZE_PRESETS
from .feeds import Headline, enabled_feeds, select_headlines
from .picker import Pick
from .store import ArtFilter, Store


@dataclass
class Plan:
    """How the screen is divided up before any art is chosen."""

    cols: int
    rows: int | None  # None = no height limit
    usable: int  # columns actually drawn into
    art_width: int
    art_height: int | None
    headlines: list[Headline]
    system: sysstat.SysInfo | None = None
    system_cfg: dict | None = None  # possibly reduced to alerts only on short screens

    def art_filter(self, cfg: dict) -> ArtFilter:
        art, display = cfg["art"], cfg["display"]
        return ArtFilter(
            categories=list(art.get("categories") or []) or None,
            min_width=min(max(int(display.get("min_width", 1)), 1), self.art_width),
            max_width=self.art_width,
            min_height=max(int(display.get("min_height", 1)), 1),
            max_height=self.art_height,
            hide_flagged=bool(art.get("hide_flagged", True)),
        )


@dataclass
class Result:
    text: str
    pick: Pick
    plan: Plan
    color: str
    glyphs: str
    sections: dict[str, tuple[int, int]]
    private: bool = False


def resolve_size(display: dict, measured: tuple[int, int] | None,
                 cols: int | None = None, rows: int | None = None) -> tuple[int, int | None]:
    """Screen area the MOTD may use -> (cols, rows or None for "no limit")."""
    mode = display.get("size", "auto")
    fallback = (int(display.get("width", 80)), int(display.get("height", 24)))
    if mode == "custom":
        c, r = fallback
    elif mode == "auto-width":
        c, r = (measured or fallback)[0], 0
    elif mode in SIZE_PRESETS and SIZE_PRESETS[mode][1] is not None:
        c, r = SIZE_PRESETS[mode][1], SIZE_PRESETS[mode][2]
    else:
        c, r = measured or fallback
    if measured and mode not in ("auto", "auto-width"):
        c = min(c, measured[0])  # a preset wider than the window would just wrap
    if cols:
        c = cols
    if rows is not None:
        r = rows
    return max(int(c), 20), (int(r) or None) if r is not None else None


def current_headlines(cfg: dict, store: Store, now: float) -> list[Headline]:
    news = cfg["news"]
    if not news.get("enabled"):
        return []
    feeds = enabled_feeds(news)
    return select_headlines(
        store.headlines([f.url for f in feeds]), feeds,
        count=int(news.get("count", 5)), per_source=int(news.get("per_source", 2)),
        max_age_hours=float(news.get("max_age_hours", 36)), now=now,
    )


def is_private(cfg: dict) -> bool:
    """Privacy mode: the config switch, or HOTHELLO_PRIVACY=1 for a single session."""
    env = os.environ.get("HOTHELLO_PRIVACY", "").strip().lower()
    if env in ("1", "on", "yes", "true"):
        return True
    if env in ("0", "off", "no", "false"):
        return False
    return bool(cfg.get("privacy", {}).get("enabled"))


def plan(cfg: dict, store: Store, *, measured: tuple[int, int] | None, cols: int | None = None,
         rows: int | None = None, now: float | None = None, glyphs: str | None = None,
         private: bool | None = None) -> Plan:
    display, theme_cfg = cfg["display"], cfg["theme"]
    cols, rows = resolve_size(display, measured, cols, rows)
    usable = cols - 1  # never fill the last column: some consoles wrap early
    headlines = current_headlines(cfg, store, now or time.time())
    frame = display.get("frame", "none")
    art_rows = 2 if frame != "none" else (1 if display.get("credit", True) or display.get("title", True) else 0)
    header_rows = 2 if theme_cfg.get("header", True) and theme_cfg.get("segments") else 0
    private = is_private(cfg) if private is None else private
    reserve = int(display.get("reserve_rows", 2))

    system_cfg = dict(cfg.get("system") or {})
    info = sysstat.gather(system_cfg) if system_cfg.get("enabled") else None
    gl = themes.resolve_glyphs(glyphs or theme_cfg.get("glyphs", "auto"))
    plain = themes.Painter("none")
    theme = themes.get_theme(theme_cfg.get("name", themes.DEFAULT_THEME))

    def system_rows() -> int:
        lines = render.system_block(info, system_cfg, theme, gl, plain, usable, private=private)
        return len(lines) + 1 if lines else 0

    sys_rows = system_rows()

    def art_room() -> int | None:
        if rows is None:
            return None
        news_rows = len(headlines) + 2 if headlines else 0
        return rows - header_rows - sys_rows - news_rows - art_rows - reserve

    # On short screens the art gets room first: drop headlines, then the system grid
    # (its alerts, like "restart required", stay).
    if cfg["art"].get("enabled", True):
        target = max(int(display.get("min_height", 4)), 6)
        while headlines and (room := art_room()) is not None and room < target:
            headlines.pop()
        if info is not None and (room := art_room()) is not None and room < target:
            system_cfg["items"] = []
            sys_rows = system_rows()
    return Plan(cols, rows, usable, usable - (4 if frame != "none" else 0), art_room(), headlines, info, system_cfg)


def build(cfg: dict, store: Store, *, cols: int | None = None, rows: int | None = None,
          color: str | None = None, glyphs: str | None = None, hyperlinks: bool | None = None,
          shell: str | None = None, now: float | None = None, dry_run: bool = False,
          prefer_id: int | None = None, measured: tuple[int, int] | None | str = "auto",
          private: bool | None = None) -> Result:
    now = now or time.time()
    display, art_cfg, news_cfg, theme_cfg = cfg["display"], cfg["art"], cfg["news"], cfg["theme"]
    if measured == "auto":
        measured = term.measure()
    private = is_private(cfg) if private is None else private
    p = plan(cfg, store, measured=measured, cols=cols, rows=rows, now=now, glyphs=glyphs,  # type: ignore[arg-type]
             private=private)

    theme = themes.get_theme(theme_cfg.get("name", themes.DEFAULT_THEME))
    gl = themes.resolve_glyphs(glyphs or theme_cfg.get("glyphs", "auto"))
    depth = color or theme_cfg.get("color", "auto")
    if depth == "auto":
        depth = term.detect_color()
    painter = themes.Painter(depth)
    links = hyperlinks if hyperlinks is not None else term.detect_hyperlinks(news_cfg.get("hyperlinks", "auto"))

    pick = Pick(None, [])
    if art_cfg.get("enabled", True):
        pick = picker.pick(store, art_cfg, display, max_width=p.art_width, max_height=p.art_height,
                           now=now, dry_run=dry_run, prefer_id=prefer_id)

    category = None
    if pick.art and pick.art.categories:
        selected = set(art_cfg.get("categories") or [])
        category = next((name for cid, name in pick.art.categories if cid in selected), pick.art.categories[0][1])
    header = ""
    if theme_cfg.get("header", True):
        alias = str(cfg.get("privacy", {}).get("alias") or "friend")
        header = render.header_line(
            sysinfo.segments(theme_cfg, now=now, shell=shell, category=category, private=private, alias=alias),
            theme, gl, painter, p.usable,
        )
    art_lines = render.art_block(pick, theme, theme_cfg.get("art_style", "theme"), gl, painter, p.usable, display, links)
    notice: list[str] = []
    if art_cfg.get("enabled", True) and not art_lines and store.art_count() == 0:
        notice = render.first_run_notice(painter, theme, gl, p.usable)
    news_lines = render.news_block(p.headlines, theme, gl, painter, p.usable, news_cfg, links, now)
    system_lines = render.system_block(p.system, p.system_cfg or {}, theme, gl, painter, p.usable,
                                       theme_cfg.get("timezone"), private=private)
    text, sections = render.compose(header=header, system=system_lines, art=art_lines, notice=notice,
                                    news=news_lines)
    return Result(text, pick, p, depth, gl.name, sections, private)
