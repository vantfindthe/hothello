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


def _prepare_stdout() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass


def cmd_show(args) -> int:
    """Print the MOTD.  Never raises: a broken greeting must not break a login shell."""
    try:
        from . import animate, motd, refresh, term, themes

        term.enable_vt()
        cfg = config.load()
        store = _store()
        res = motd.build(
            cfg, store, cols=args.width, rows=args.height, color=args.color, glyphs=args.glyphs,
            hyperlinks={"on": True, "off": False}.get(args.links or ""), shell=args.shell,
            dry_run=args.dry_run, private=True if args.private else None,
        )
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(res.text)
        else:
            _prepare_stdout()
            anim = cfg["animation"]
            style = args.animate or anim.get("style", "none")
            if args.no_animate or os.environ.get("MOTDPLUS_NO_ANIMATION"):
                style = "none"
            measured = term.measure()
            art_lines = res.sections.get("art")
            animate.play(
                res.text, style=style, speed=anim.get("speed", "normal"), width=res.plan.usable,
                term_rows=measured[1] if measured else None, painter=themes.Painter(res.color),
                ascii_only=res.glyphs == "ascii", only=art_lines if anim.get("target") == "art" else None,
                focus=art_lines,
            )
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


def cmd_tui(args) -> int:
    try:
        from .tui import run
    except ImportError as e:
        print(f"The settings UI needs Textual ({e}).  Install it with:  pip install textual")
        return 1
    return run()


OVERVIEW = """\
commands:
  show / preview            print the MOTD (preview doesn't use up the art)
  features                  list features;  on / off / toggle FEATURE ...  to show or hide them
                            e.g.  motdplus off headlines credit   ·   motdplus on privacy
  privacy [on|off]          hide names, addresses and versions (for screen recordings)
  theme [NAME]              list themes with examples, or pick one  (--import-omp for oh-my-posh)
  font [NAME]               list glyph sets / fonts with examples, or pick one
  color [MODE]              colour depth, with examples
  frame [STYLE]             frames around the art, with examples
  size [NAME|WxH]           screen size presets for small or large displays
  cycle [MODE]              how art is chosen (--every login|hourly|daily, --prefer any|large)
  categories [SEARCH]       list art categories; --add/--remove/--only NAME|GROUP|ID, --clear
  feeds                     news feeds; --add/--remove ID|URL
  headlines                 --count, --per-source, --max-age
  animation [STYLE]         login animations: lines, slide, wipe, rain, decode, nuke, random (--try)
  greeting [TEXT]           the greeting text
  get / set / reset         read or change any setting directly
  refresh · status · install · uninstall · config (the settings UI, also: no command)
"""


def main(argv: list[str] | None = None) -> int:
    from . import commands as c

    p = argparse.ArgumentParser(
        prog="motdplus", description="A fresh piece of ASCII art, the news and your system at every login.",
        epilog=OVERVIEW, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"motdplus {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND")

    def display_flags(sp, preview: bool) -> None:
        sp.add_argument("--width", type=int, help="override the width")
        sp.add_argument("--height", type=int, help="override the height (0 = no limit)")
        sp.add_argument("--color", choices=["truecolor", "256", "16", "none"])
        sp.add_argument("--glyphs", choices=["nerd", "powerline", "unicode", "ascii"])
        sp.add_argument("--private", action="store_true", help="privacy mode for this run")
        sp.add_argument("--animate", choices=list(c.ANIMATIONS), help="animation for this run")
        sp.add_argument("--no-animate", action="store_true", help="no animation this time")
        if preview:
            sp.set_defaults(func=cmd_show, dry_run=True, no_refresh=True, links=None, shell=None, output=None)

    s = sub.add_parser("show", help="print the MOTD (what the login hook runs)")
    display_flags(s, preview=False)
    s.add_argument("--links", choices=["on", "off"], help="OSC 8 hyperlinks")
    s.add_argument("--shell", help="shell name for the 'shell' segment")
    s.add_argument("--dry-run", action="store_true", help="don't record the pick or refresh anything")
    s.add_argument("--no-refresh", action="store_true", help="don't start a background refresh")
    s.add_argument("--output", help="write to a file instead of stdout")
    s.set_defaults(func=cmd_show)

    display_flags(sub.add_parser("preview", help="show the next MOTD without using it up"), preview=True)

    s = sub.add_parser("features", help="list features and whether they're on")
    s.set_defaults(func=c.cmd_features)
    for mode, text in (("on", "show / enable features"), ("off", "hide / disable features"),
                       ("toggle", "flip features")):
        s = sub.add_parser(mode, help=text, aliases=({"on": ["enable", "unhide"], "off": ["disable", "hide"]}
                                                     .get(mode, [])))
        s.add_argument("features", nargs="+", metavar="FEATURE", help="see: motdplus features")
        s.set_defaults(func=c.cmd_switch, mode=mode)

    s = sub.add_parser("privacy", help="privacy mode for screen recordings", aliases=["private"])
    s.add_argument("state", nargs="?", choices=["on", "off"])
    s.add_argument("--alias", help="name shown instead of your user name")
    s.set_defaults(func=c.cmd_privacy)

    s = sub.add_parser("theme", help="list themes with examples, or choose one", aliases=["themes"])
    s.add_argument("name", nargs="?")
    s.add_argument("--import-omp", nargs="?", const="", metavar="CONFIG",
                   help="import an oh-my-posh theme (default: the one your shell uses) and use it")
    s.set_defaults(func=c.cmd_theme)

    s = sub.add_parser("font", help="list fonts / glyph sets with examples, or choose one",
                       aliases=["fonts", "glyphs"])
    s.add_argument("name", nargs="?")
    s.set_defaults(func=c.cmd_font)

    s = sub.add_parser("color", help="list colour depths with examples, or choose one",
                       aliases=["colors", "colour"])
    s.add_argument("mode", nargs="?")
    s.set_defaults(func=c.cmd_color)

    s = sub.add_parser("frame", help="list frame styles with examples, or choose one", aliases=["frames"])
    s.add_argument("style", nargs="?")
    s.set_defaults(func=c.cmd_frame)

    s = sub.add_parser("size", help="list screen sizes, or choose a preset / WxH", aliases=["sizes"])
    s.add_argument("size", nargs="?", metavar="NAME|WxH")
    s.set_defaults(func=c.cmd_size)

    s = sub.add_parser("cycle", help="how art is chosen and how often it changes")
    s.add_argument("mode", nargs="?", help="shuffle, rotate or random")
    s.add_argument("--every", choices=list(c.CHANGE_MODES))
    s.add_argument("--prefer", choices=list(c.PREFER_MODES))
    s.set_defaults(func=c.cmd_cycle)

    s = sub.add_parser("categories", help="list art categories, or choose which to cycle", aliases=["category"])
    s.add_argument("search", nargs="?")
    s.add_argument("--add", nargs="+", metavar="NAME")
    s.add_argument("--remove", nargs="+", metavar="NAME")
    s.add_argument("--only", nargs="+", metavar="NAME")
    s.add_argument("--clear", action="store_true", help="back to every category")
    s.add_argument("--selected", action="store_true", help="list only the chosen ones")
    s.set_defaults(func=c.cmd_categories)

    s = sub.add_parser("feeds", help="list news feeds, or add / remove them", aliases=["feed"])
    s.add_argument("--add", nargs="+", metavar="ID|URL")
    s.add_argument("--remove", nargs="+", metavar="ID|URL")
    s.add_argument("--name", help="name for a custom feed")
    s.set_defaults(func=c.cmd_feeds)

    s = sub.add_parser("headlines", help="how many headlines, per source, how old", aliases=["news"])
    s.add_argument("--count", type=int)
    s.add_argument("--per-source", type=int)
    s.add_argument("--max-age", type=int, metavar="HOURS")
    s.set_defaults(func=c.cmd_headlines)

    s = sub.add_parser("animation", help="list login animations, or choose one", aliases=["animations", "animate"])
    s.add_argument("style", nargs="?")
    s.add_argument("--speed", choices=list(c.SPEEDS))
    s.add_argument("--target", choices=["all", "art"], help="animate everything or just the art")
    s.add_argument("--try", dest="try_it", action="store_true", help="play it now (without saving the style)")
    s.set_defaults(func=c.cmd_animation)

    s = sub.add_parser("greeting", help="show or change the greeting text")
    s.add_argument("text", nargs="*")
    s.set_defaults(func=c.cmd_greeting)

    s = sub.add_parser("get", help="print settings (all, or one dotted key like display.width)")
    s.add_argument("key", nargs="?")
    s.set_defaults(func=c.cmd_get)

    s = sub.add_parser("set", help="change any setting: motdplus set display.width 100")
    s.add_argument("key")
    s.add_argument("value", nargs="+")
    s.set_defaults(func=c.cmd_set)

    s = sub.add_parser("reset", help="restore default settings")
    s.add_argument("section", nargs="?", help="all (default), art, display, news, system, privacy, animation, theme")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(func=c.cmd_reset)

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

    s = sub.add_parser("config", help="open the settings UI (same as no command)", aliases=["ui", "tui"])
    s.set_defaults(func=cmd_tui)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        return cmd_tui(args)
    return args.func(args)
