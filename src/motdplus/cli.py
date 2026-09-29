"""Command line: `motdplus` opens the settings UI; subcommands do everything else."""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

from . import __version__, config, paths


def _store():
    from .store import Store

    return Store()


def _write(text: str) -> None:
    try:
        sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    sys.stdout.write(text)
    sys.stdout.flush()


def cmd_show(args) -> int:
    """Print the MOTD.  Never raises: a broken greeting must not break a login shell."""
    try:
        from . import motd, refresh, term

        term.enable_vt()
        cfg = config.load()
        store = _store()
        res = motd.build(
            cfg, store, cols=args.width, rows=args.height, color=args.color, glyphs=args.glyphs,
            hyperlinks={"on": True, "off": False}.get(args.links or ""), shell=args.shell,
            dry_run=args.dry_run,
        )
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(res.text)
        else:
            _write(res.text)
        if not args.dry_run and not args.no_refresh:
            now = time.time()
            store.kv_set("pool_left", res.pick.pool_left)
            if ((cfg["art"].get("enabled", True) and refresh.catalog_due(store, now))
                    or refresh.art_due(cfg, store, now, res.pick.pool_left)
                    or refresh.news_due(cfg, store, now)):
                refresh.spawn_background()
    except Exception:
        if os.environ.get("MOTDPLUS_DEBUG"):
            raise
    return 0


def cmd_refresh(args) -> int:
    from . import refresh

    cfg = config.load()
    store = _store()
    everything = not (args.art or args.news or args.catalog)
    lines: list[str] = []

    def log(msg: str) -> None:
        lines.append(msg)
        if not args.quiet:
            print(msg, flush=True)

    with refresh.Lock() as got:
        if not got:
            log("another refresh is already running")
            return 0
        try:
            refresh.run(
                cfg, store, art=everything or args.art, news=everything or args.news,
                catalog=True if args.catalog else None, if_due=args.if_due, log=log,
            )
        except Exception as e:
            log(f"error: {e}")
            raise
        finally:
            try:
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                paths.log_file().write_text(f"[{stamp}]\n" + "\n".join(lines) + "\n", encoding="utf-8")
            except OSError:
                pass
    return 0


def cmd_install(args) -> int:
    from . import hooks, refresh

    available = hooks.targets()
    keys = args.target or hooks.default_targets()
    status = 0
    for key in keys:
        target = available.get(key)
        if target is None:
            print(f"unknown target {key!r}; choose from: {', '.join(available)}")
            status = 1
            continue
        if target.system:
            if os.geteuid() != 0:  # type: ignore[attr-defined]
                print(f"{target.label}: needs root. Run:\n  sudo {sys.executable} -m motdplus install --target {key}")
                status = 1
                continue
            hooks.seed_system_home()
            os.environ["MOTDPLUS_HOME"] = hooks.SYSTEM_HOME
        print(f"{target.label}: {hooks.install(target, args.python)}")
    if args.hushlogin:
        print(hooks.set_hushlogin(True))
    if not args.no_fetch:
        store = _store()
        if store.art_count() == 0 or not store.groupings():
            print("fetching a first batch of art and headlines ...", flush=True)
            with refresh.Lock() as got:
                if got:
                    refresh.run(config.load(), store, log=lambda m: print("  " + m, flush=True))
    return status


def cmd_uninstall(args) -> int:
    from . import hooks

    available = hooks.targets()
    keys = args.target or [k for k, t in available.items() if hooks.is_installed(t)]
    if not keys:
        print("no motdplus hooks are installed")
    for key in keys:
        if target := available.get(key):
            print(f"{target.label}: {hooks.uninstall(target)}")
    if args.hushlogin:
        print(hooks.set_hushlogin(False))
    return 0


def _ago(ts: float | None) -> str:
    if not ts:
        return "never"
    from .render import format_age

    return format_age(time.time() - ts) + " ago"


def cmd_status(args) -> int:
    from . import hooks, term, themes
    from .feeds import enabled_feeds
    from .motd import resolve_size

    cfg = config.load()
    store = _store()
    print(f"motdplus {__version__}   python {sys.executable}")
    print(f"config  {paths.config_file()}")
    print(f"cache   {paths.db_file()}")
    print()
    cats = store.categories()
    selected = cfg["art"]["categories"]
    print(f"art        {store.art_count()} pieces cached from {sum(1 for c in cats if c['cached'])} categories;"
          f" cycling {'all' if not selected else len(selected)} categories ({cfg['art']['cycle']}, every {cfg['art']['change']})")
    print(f"           catalog {_ago(store.kv_get('catalog_at'))}, art fetched {_ago(store.kv_get('last_art_refresh'))}")
    feeds = enabled_feeds(cfg["news"])
    fstat = store.feed_status()
    print(f"news       {'on' if cfg['news']['enabled'] else 'off'}, {len(feeds)} feeds, fetched {_ago(store.kv_get('last_news_refresh'))}")
    for f in feeds:
        s = fstat.get(f.url)
        state = "not fetched yet" if s is None else (f"{s['items']} items" if s["ok"] else f"ERROR {s['error']}")
        print(f"             {f.name}: {state}")
    measured = term.measure()
    cols, rows = resolve_size(cfg["display"], measured)
    print(f"terminal   {measured[0]}x{measured[1]}" if measured else "terminal   (not a terminal)", end="")
    print(f" -> using {cols}x{rows or 'any'} ({cfg['display']['size']})")
    color = cfg["theme"]["color"]
    print(f"theme      {cfg['theme']['name']}, glyphs {themes.resolve_glyphs(cfg['theme']['glyphs']).name},"
          f" colour {term.detect_color() if color == 'auto' else color}")
    print()
    for key, target in hooks.relevant_targets().items():
        mark = "installed" if hooks.is_installed(target) else "-"
        print(f"hook       {target.label:<48} {mark}")
    if os.name != "nt":
        print(f"hushlogin  {'on (system login message hidden)' if hooks.hushlogin_enabled() else 'off'}")
    if paths.log_file().exists():
        print("\nlast background refresh:")
        print("  " + paths.log_file().read_text(encoding="utf-8").strip().replace("\n", "\n  "))
    return 0


def cmd_themes(args) -> int:
    from . import render, sysinfo, themes

    if args.import_omp is not None:
        source = args.import_omp or themes.detect_omp_config()
        if not source:
            print("couldn't find your oh-my-posh config; pass a name or path: motdplus themes --import-omp PATH")
            return 1
        theme = themes.import_omp(source)
        print(f"imported {source!r} as theme {theme.key!r}")
        if args.use:
            cfg = config.load()
            cfg["theme"]["name"] = theme.key
            config.save(cfg)
            print("and made it the active theme")
        return 0
    cfg = config.load()
    gl = themes.resolve_glyphs(cfg["theme"]["glyphs"])
    painter = themes.Painter("truecolor" if args.color is None else args.color)
    items = sysinfo.segments({**cfg["theme"], "segments": ["user", "host", "datetime"]}, now=time.time())
    for key, theme in themes.all_themes().items():
        active = "*" if key == cfg["theme"]["name"] else " "
        print(f"{active} {key:<20} {render.header_line(items, theme, gl, painter, 60)}")
    return 0


def cmd_categories(args) -> int:
    store = _store()
    cfg = config.load()
    selected = set(cfg["art"]["categories"])
    groups = {g["id"]: g["name"] for g in store.groupings()}
    needle = (args.search or "").casefold()
    for c in store.categories():
        group = groups.get(c["grouping_id"], "?")
        if needle and needle not in c["name"].casefold() and needle not in group.casefold():
            continue
        mark = "x" if c["id"] in selected else " "
        print(f"[{mark}] {c['id']:>4}  {group} / {c['name']}  ({c['cached']}/{c['count'] or '?'} cached)")
    return 0


def cmd_tui(args) -> int:
    try:
        from .tui import run
    except ImportError as e:
        print(f"The settings UI needs Textual ({e}).  Install it with:  pip install textual")
        return 1
    return run()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="motdplus", description="A fresh piece of ASCII art and the news at every login.")
    p.add_argument("--version", action="version", version=f"motdplus {__version__}")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("show", help="print the MOTD (what the login hook runs)")
    s.add_argument("--width", type=int, help="override the width")
    s.add_argument("--height", type=int, help="override the height (0 = no limit)")
    s.add_argument("--color", choices=["truecolor", "256", "16", "none"])
    s.add_argument("--glyphs", choices=["nerd", "powerline", "unicode", "ascii"])
    s.add_argument("--links", choices=["on", "off"], help="OSC 8 hyperlinks")
    s.add_argument("--shell", help="shell name for the 'shell' segment")
    s.add_argument("--dry-run", action="store_true", help="don't record the pick or refresh anything")
    s.add_argument("--no-refresh", action="store_true", help="don't start a background refresh")
    s.add_argument("--output", help="write to a file instead of stdout")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("preview", help="show what the next MOTD looks like, without using it up")
    s.add_argument("--width", type=int)
    s.add_argument("--height", type=int)
    s.add_argument("--color", choices=["truecolor", "256", "16", "none"])
    s.add_argument("--glyphs", choices=["nerd", "powerline", "unicode", "ascii"])
    s.set_defaults(func=cmd_show, dry_run=True, no_refresh=True, links=None, shell=None, output=None)

    s = sub.add_parser("refresh", help="fetch new art and headlines now")
    s.add_argument("--art", action="store_true", help="only art")
    s.add_argument("--news", action="store_true", help="only headlines")
    s.add_argument("--catalog", action="store_true", help="re-read the category list")
    s.add_argument("--if-due", action="store_true", help="skip anything that isn't due yet")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(func=cmd_refresh)

    s = sub.add_parser("install", help="add the login hook")
    s.add_argument("--target", action="append", help="powershell, pwsh, bash, zsh, fish or update-motd (repeatable)")
    s.add_argument("--python", help="interpreter the hook should run (default: this one)")
    s.add_argument("--hushlogin", action="store_true", help="also hide the system login message (~/.hushlogin)")
    s.add_argument("--no-fetch", action="store_true", help="don't download a first batch of art")
    s.set_defaults(func=cmd_install)

    s = sub.add_parser("uninstall", help="remove the login hook(s)")
    s.add_argument("--target", action="append")
    s.add_argument("--hushlogin", action="store_true", help="also remove ~/.hushlogin")
    s.set_defaults(func=cmd_uninstall)

    s = sub.add_parser("status", help="paths, cache, feeds and hook status")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("themes", help="list themes, or import one from oh-my-posh")
    s.add_argument("--import-omp", nargs="?", const="", metavar="CONFIG",
                   help="oh-my-posh theme name or config path (default: the one your shell uses)")
    s.add_argument("--use", action="store_true", help="make the imported theme active")
    s.add_argument("--color", choices=["truecolor", "256", "16", "none"])
    s.set_defaults(func=cmd_themes)

    s = sub.add_parser("categories", help="list art categories")
    s.add_argument("search", nargs="?")
    s.set_defaults(func=cmd_categories)

    s = sub.add_parser("config", help="open the settings UI (same as no arguments)")
    s.set_defaults(func=cmd_tui)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        return cmd_tui(args)
    return args.func(args)
