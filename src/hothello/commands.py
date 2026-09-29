"""Command-line settings: feature switches, privacy, and list-or-set commands for
themes, fonts, colours, frames, sizes, cycling, categories, feeds and animations.

Every "list" shows a small live example drawn with your current settings."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Callable

from . import config, hooks, render, themes
from .animate import SPEEDS, STYLES as ANIMATIONS
from .config import CHANGE_MODES, CYCLE_MODES, FRAMES, PREFER_MODES, SIZE_PRESETS
from .sysinfo import SEGMENT_CHOICES
from .sysstat import ITEMS as SYSTEM_ITEMS
from .textutil import visible_width


def _out(text: str = "") -> None:
    if getattr(sys.stdout, "errors", "replace") != "replace":
        try:
            sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    print(text)


def _painter(cfg: dict) -> themes.Painter:
    from . import term

    term.enable_vt()
    depth = cfg["theme"].get("color", "auto")
    if not sys.stdout.isatty():
        return themes.Painter("none")
    return themes.Painter(term.detect_color() if depth == "auto" else depth)


def _mark(active: bool) -> str:
    return "*" if active else " "


def _saved(cfg: dict, message: str) -> int:
    config.save(cfg)
    _out(message)
    _out("  (see it with: hothello preview)")
    return 0


def _pick(value: str, choices, what: str) -> str | None:
    """Exact or unique-prefix match (case-insensitive)."""
    options = list(choices)
    lowered = value.lower()
    if lowered in options:
        return lowered
    matches = [o for o in options if o.startswith(lowered)]
    if len(matches) == 1:
        return matches[0]
    _out(f"unknown {what} {value!r}; choose from: {', '.join(options)}")
    return None


# -- feature switches -------------------------------------------------------------------------------

@dataclass
class Feature:
    name: str
    help: str
    get: Callable[[dict], bool]
    set: Callable[[dict, bool], None]
    aliases: tuple[str, ...] = ()
    system_file: bool = False  # changes a file outside the config (hushlogin)


def _flag(section: str, key: str) -> tuple[Callable[[dict], bool], Callable[[dict, bool], None]]:
    return (lambda c: bool(c[section][key]), lambda c, v: c[section].__setitem__(key, v))


def _toggle_value(section: str, key: str, off: str, default_on: str, memory_key: str):
    """For settings whose "off" is a value (frame none, colour none ...): remember
    the previous value so switching back on restores it."""

    def get(c: dict) -> bool:
        return c[section][key] != off

    def put(c: dict, v: bool) -> None:
        if v:
            c[section][key] = c[section].get(memory_key) or default_on
        elif c[section][key] != off:
            c[section][memory_key] = c[section][key]
            c[section][key] = off

    return get, put


def _network(c: dict, v: bool) -> None:
    items = set(c["system"]["items"]) | {"network"} if v else set(c["system"]["items"]) - {"network"}
    c["system"]["items"] = [k for k in SYSTEM_ITEMS if k in items]


FEATURES: list[Feature] = [
    Feature("art", "the ASCII art", *_flag("art", "enabled")),
    Feature("headlines", "news headlines", *_flag("news", "enabled"), aliases=("news",)),
    Feature("system", "the System section (load, disk, memory, users ...)", *_flag("system", "enabled"),
            aliases=("sysinfo", "stats")),
    Feature("header", "the powerline header bar", *_flag("theme", "header"), aliases=("bar",)),
    Feature("title", "art names (frame title / credit line)", *_flag("display", "title"), aliases=("names", "name")),
    Feature("credit", "art sources: artist and asciiart.website link", *_flag("display", "credit"),
            aliases=("source", "sources", "attribution", "artist")),
    Feature("frame", "the frame around the art", *_toggle_value("display", "frame", "none", "rounded", "last_frame"),
            aliases=("border",)),
    Feature("badges", "news source badges (BBC, NPR ...)", *_flag("news", "show_source"), aliases=("badge",)),
    Feature("ages", "headline ages (2h, 1d)", *_flag("news", "show_age"), aliases=("age",)),
    Feature("links", "clickable links (OSC 8)", *_toggle_value("news", "hyperlinks", "off", "on", "last_hyperlinks"),
            aliases=("hyperlinks",)),
    Feature("bars", "usage bars in the System section", *_flag("system", "bars")),
    Feature("alerts", "pending updates / restart required / new release", *_flag("system", "alerts")),
    Feature("lastlogin", "last login time and address", *_flag("system", "last_login"), aliases=("login",)),
    Feature("network", "IP addresses in the System section",
            lambda c: "network" in c["system"]["items"], _network, aliases=("ip", "ips", "addresses")),
    Feature("privacy", "privacy mode for recordings: hide names, addresses, versions",
            *_flag("privacy", "enabled"), aliases=("private", "streamer", "recording")),
    Feature("animation", "the login animation",
            *_toggle_value("animation", "style", "none", "random", "last_style"), aliases=("animations", "animate")),
    Feature("color", "colours", *_toggle_value("theme", "color", "none", "auto", "last_color"),
            aliases=("colour", "colors", "colours")),
    Feature("flagged", "art the site flags for nudity / explicit content",
            lambda c: not c["art"]["hide_flagged"], lambda c, v: c["art"].__setitem__("hide_flagged", not v),
            aliases=("nsfw",)),
]
if os.name != "nt":
    FEATURES.append(Feature("hushlogin", "hide the system's plain login message (~/.hushlogin)",
                            lambda c: hooks.hushlogin_enabled(), lambda c, v: None, system_file=True))
FEATURE_NAMES = {name: f for f in FEATURES for name in (f.name, *f.aliases)}


def cmd_features(args) -> int:
    cfg = config.load()
    _out("Features (turn them with: hothello on|off|toggle NAME ...)\n")
    for f in FEATURES:
        state = "on " if f.get(cfg) else "off"
        alias = f"  [{', '.join(f.aliases[:3])}]" if f.aliases else ""
        _out(f"  {state}  {f.name:<10} {f.help}{alias}")
    return 0


def cmd_switch(args) -> int:
    cfg = config.load()
    status = 0
    for name in args.features:
        feature = FEATURE_NAMES.get(name.lower())
        if feature is None:
            _out(f"unknown feature {name!r}; see: hothello features")
            status = 1
            continue
        value = (not feature.get(cfg)) if args.mode == "toggle" else args.mode == "on"
        if feature.system_file:
            _out(hooks.set_hushlogin(value))
            continue
        feature.set(cfg, value)
        _out(f"{feature.name}: {'on' if feature.get(cfg) else 'off'}  ({feature.help})")
        if feature.name == "privacy" and value:
            _out("  hidden: user name, host, IP addresses, last-login address, OS/kernel versions,")
            _out("          uptime, memory/disk totals, pending updates and restart status")
    config.save(cfg)
    if status == 0:
        _out("  (see it with: hothello preview)")
    return status


def cmd_privacy(args) -> int:
    cfg = config.load()
    if args.state:
        cfg["privacy"]["enabled"] = args.state == "on"
    if args.alias is not None:
        cfg["privacy"]["alias"] = args.alias
    if args.state or args.alias is not None:
        config.save(cfg)
    p = cfg["privacy"]
    _out(f"privacy mode: {'on' if p['enabled'] else 'off'}   (your name shows as {p['alias']!r})")
    _out("  hides: user name, host name, IP addresses, last-login address, OS and kernel versions,")
    _out("         uptime, memory/disk totals, pending updates and restart status")
    _out("  one session only: HOTHELLO_PRIVACY=1 hothello preview   ·   or: hothello preview --private")
    return 0


# -- themes, fonts, colours, frames ------------------------------------------------------------

def _swatch(theme: themes.Theme, glyphs: themes.Glyphs, painter: themes.Painter, width: int = 14) -> str:
    text = ("#" if glyphs.name == "ascii" else "▓") * width
    style = theme.art_style if theme.art_style != "plain" else "solid"
    color_at = themes.art_color_fn(style, theme.art_colors or [theme.text or "default"], "horizontal", width, 1)
    return render._colorize(text, 0, color_at, painter, themes.parse_color(theme.text))


def cmd_theme(args) -> int:
    cfg = config.load()
    if args.import_omp is not None:
        source = args.import_omp or themes.detect_omp_config()
        if not source:
            _out("couldn't find your oh-my-posh config; pass a name or path: hothello theme --import-omp PATH")
            return 1
        theme = themes.import_omp(source)
        _out(f"imported {source!r} as theme {theme.key!r}")
        cfg["theme"]["name"] = theme.key
        return _saved(cfg, f"theme: {theme.key}")
    available = themes.all_themes()
    if args.name:
        key = _pick(args.name, available, "theme")
        if key is None:
            return 1
        cfg["theme"]["name"] = key
        return _saved(cfg, f"theme: {key} ({available[key].name})")
    glyphs = themes.resolve_glyphs(cfg["theme"]["glyphs"])
    painter = _painter(cfg)
    items = [("user", "you"), ("host", "box"), ("datetime", "09:41")]
    _out("Themes (set with: hothello theme NAME)\n")
    for key, theme in available.items():
        head = render.header_line(items, theme, glyphs, painter, 36)
        pad = " " * max(36 - visible_width(head), 0)
        _out(f" {_mark(key == cfg['theme']['name'])} {key:<18} {head}{pad}  {_swatch(theme, glyphs, painter)}"
             f"  {theme.name if theme.source == 'built-in' else 'yours: ' + theme.name}")
    _out("\n  also: hothello theme --import-omp [NAME|PATH]   (copy an oh-my-posh theme's colours)")
    return 0


FONT_HELP = {
    "auto": "detect: Nerd Font if oh-my-posh/starship is installed, else plain Unicode",
    "nerd": "a Nerd Font: icons plus rounded, slanted and flame separators",
    "powerline": "a Powerline-patched font: arrow separators, no icons",
    "unicode": "any modern font: flat colour blocks, box drawing, ▸ bullets",
    "ascii": "anything at all, even a serial console: plain ASCII only",
}


def cmd_font(args) -> int:
    cfg = config.load()
    if args.name:
        key = _pick(args.name, FONT_HELP, "font")
        if key is None:
            return 1
        cfg["theme"]["glyphs"] = key
        return _saved(cfg, f"font / glyphs: {key}")
    painter = _painter(cfg)
    theme = themes.get_theme(cfg["theme"]["name"])
    current = cfg["theme"]["glyphs"]
    detected = themes.resolve_glyphs("auto").name
    _out("Fonts / glyph sets (set with: hothello font NAME)")
    _out("If the example shows boxes or question marks, your terminal font lacks those glyphs.\n")
    items = [("user", "you"), ("host", "box"), ("uptime", "up 3d")]
    for key, text in FONT_HELP.items():
        g = themes.GLYPH_SETS[detected if key == "auto" else key]
        frame = themes.FRAME_CHARS["ascii" if g.name == "ascii" else "rounded"]
        bar = "###--" if g.name == "ascii" else "▰▰▰▱▱"
        sample = (render.header_line(items, theme, g, painter, 40) + "  " + g.bullet + " "
                  + bar + "  " + frame[0] + frame[4] * 2 + frame[1])
        note = f" (now: {detected})" if key == "auto" else ""
        _out(f" {_mark(key == current)} {key:<10} {sample}")
        _out(f"   {'':<10} {text}{note}")
    return 0


COLOR_HELP = {
    "auto": "detect from the terminal (COLORTERM, TERM, Windows Terminal ...)",
    "truecolor": "24-bit: smooth gradients (most modern terminals)",
    "256": "xterm 256 colours",
    "16": "the terminal's own 16-colour palette",
    "none": "no colour at all",
}


def cmd_color(args) -> int:
    cfg = config.load()
    if args.mode:
        key = _pick(args.mode, COLOR_HELP, "colour mode")
        if key is None:
            return 1
        cfg["theme"]["color"] = key
        return _saved(cfg, f"colour: {key}")
    from . import term

    theme = themes.get_theme(cfg["theme"]["name"])
    glyphs = themes.resolve_glyphs(cfg["theme"]["glyphs"])
    _out("Colour depth (set with: hothello color MODE)\n")
    for key, text in COLOR_HELP.items():
        depth = term.detect_color() if key == "auto" else key
        painter = themes.Painter(depth if sys.stdout.isatty() else "none")
        rainbow = themes.Theme("x", "x", art_style="rainbow")
        _out(f" {_mark(key == cfg['theme']['color'])} {key:<10} {_swatch(rainbow, glyphs, painter, 24)}  "
             f"{_swatch(theme, glyphs, painter, 10)}  {text}" + (f" (now: {depth})" if key == "auto" else ""))
    return 0


def cmd_frame(args) -> int:
    cfg = config.load()
    if args.style:
        key = _pick(args.style, FRAMES, "frame")
        if key is None:
            return 1
        cfg["display"]["frame"] = key
        return _saved(cfg, f"frame: {key}")
    painter = _painter(cfg)
    theme = themes.get_theme(cfg["theme"]["name"])
    frame_c, title_c = themes.parse_color(theme.frame), themes.parse_color(theme.title)
    boxes = []
    for key in FRAMES:
        chars = themes.FRAME_CHARS.get(key)
        if chars:
            tl, tr, bl, br, hz, vt = chars
            box = [painter.paint(tl + hz, frame_c) + painter.paint(" fish ", title_c) + painter.paint(hz + tr, frame_c),
                   painter.paint(vt, frame_c) + " ><(((*> " + painter.paint(vt, frame_c),
                   painter.paint(bl + hz * 8 + br, frame_c)]
        else:
            box = ["   fish   ", " ><(((*>  ", "          "]
        boxes.append((f"{_mark(key == cfg['display']['frame'])}{key}", box))
    _out("Frames (set with: hothello frame STYLE)\n")
    _out("  " + "".join(name.ljust(13) for name, _ in boxes))
    for row in range(3):
        _out("  " + "".join(box[row] + "   " for _, box in boxes))
    return 0


def cmd_size(args) -> int:
    from . import term
    from .motd import resolve_size

    cfg = config.load()
    d = cfg["display"]
    if args.size:
        value = args.size.lower()
        if "x" in value and value.replace("x", "").isdigit():
            w, h = (int(v) for v in value.split("x", 1))
            d.update(size="custom", width=max(w, 20), height=max(h, 5))
            return _saved(cfg, f"size: custom {d['width']}x{d['height']}")
        key = _pick(value, SIZE_PRESETS, "size")
        if key is None:
            return 1
        d["size"] = key
        return _saved(cfg, f"size: {key} ({SIZE_PRESETS[key][0]})")
    measured = term.measure()
    cols, rows = resolve_size(d, measured)
    _out("Screen size (set with: hothello size NAME  or  hothello size 100x30)\n")
    for key, (label, _, _) in SIZE_PRESETS.items():
        extra = f"  -> {d['width']}x{d['height']}" if key == "custom" else ""
        _out(f" {_mark(key == d['size'])} {key:<11} {label}{extra}")
    here = f"{measured[0]}x{measured[1]}" if measured else "not a terminal"
    _out(f"\n  this terminal: {here}; the MOTD will use {cols}x{rows or 'any'}")
    return 0


# -- art cycling and categories -----------------------------------------------------------------

def cmd_cycle(args) -> int:
    cfg = config.load()
    art = cfg["art"]
    changed = []
    if args.mode:
        key = _pick(args.mode, CYCLE_MODES, "cycle mode")
        if key is None:
            return 1
        art["cycle"] = key
        changed.append(f"cycle: {key}")
    if args.every:
        art["change"] = args.every
        changed.append(f"new art: every {args.every}")
    if args.prefer:
        art["prefer"] = args.prefer
        changed.append(f"size preference: {args.prefer}")
    if changed:
        return _saved(cfg, "\n".join(changed))
    _out("Art cycling (set with: hothello cycle MODE [--every login|hourly|daily] [--prefer any|large])\n")
    for key, text in CYCLE_MODES.items():
        _out(f" {_mark(key == art['cycle'])} {key:<8} {text}")
    _out("")
    for key, text in CHANGE_MODES.items():
        _out(f" {_mark(key == art['change'])} --every {key:<7} {text}")
    _out("")
    for key, text in PREFER_MODES.items():
        _out(f" {_mark(key == art['prefer'])} --prefer {key:<6} {text}")
    return 0


def _resolve_categories(names: list[str], store) -> tuple[set[int], list[str]]:
    cats = store.categories()
    groups = {g["id"]: g["name"] for g in store.groupings()}
    members: dict[int, list[int]] = {}
    for cid, gid in store.category_groupings():
        members.setdefault(gid, []).append(cid)
    found: set[int] = set()
    problems = []
    for raw in names:
        term_ = raw.strip().casefold()
        if term_.isdigit():
            found.add(int(term_))
            continue
        exact = [c["id"] for c in cats if c["name"].casefold() == term_]
        group = [gid for gid, name in groups.items() if name.casefold() == term_]
        if exact:
            found.update(exact)
        elif group:
            for gid in group:
                found.update(members.get(gid, []))
        else:
            partial = [c for c in cats if term_ in c["name"].casefold()]
            if len(partial) == 1:
                found.add(partial[0]["id"])
            elif partial:
                problems.append(f"{raw!r} matches {len(partial)} categories: "
                                + ", ".join(c["name"] for c in partial[:8]) + (" ..." if len(partial) > 8 else ""))
            else:
                problems.append(f"no category or group called {raw!r}")
    return found, problems


def cmd_categories(args) -> int:
    from .store import Store

    store = Store()
    cfg = config.load()
    selected = set(cfg["art"]["categories"])
    if args.clear or args.add or args.remove or args.only:
        names = store.category_names()
        if args.clear:
            selected = set()
        for flag, op in ((args.only, "only"), (args.add, "add"), (args.remove, "remove")):
            if not flag:
                continue
            ids, problems = _resolve_categories(flag, store)
            for p in problems:
                _out(f"  {p}")
            if op == "only":
                selected = ids
            elif op == "add":
                selected |= ids
            else:
                selected -= ids
        cfg["art"]["categories"] = sorted(selected)
        shown = ", ".join(sorted(names.get(i, str(i)) for i in selected)[:12])
        more = " ..." if len(selected) > 12 else ""
        return _saved(cfg, f"cycling {len(selected)} categories: {shown}{more}" if selected
                      else "cycling every category")
    groups = {g["id"]: g["name"] for g in store.groupings()}
    needle = (args.search or "").casefold()
    rows = 0
    for c in store.categories():
        group = groups.get(c["grouping_id"], "?")
        if args.selected and c["id"] not in selected:
            continue
        if needle and needle not in c["name"].casefold() and needle not in group.casefold():
            continue
        rows += 1
        _out(f"[{'x' if c['id'] in selected else ' '}] {c['id']:>4}  {group} / {c['name']}"
             f"  ({c['cached']}/{c['count'] or '?'} cached)")
    if not rows:
        _out("no categories match" if store.groupings() else "no category list yet: run hothello refresh")
    _out(f"\n{'every category' if not selected else f'{len(selected)} selected'} · "
         "change with --add / --remove / --only NAME|GROUP|ID ...  or --clear")
    return 0


# -- news ---------------------------------------------------------------------------------------------

def cmd_feeds(args) -> int:
    from .feeds import PRESETS, PRESETS_BY_ID

    cfg = config.load()
    news = cfg["news"]
    if args.add or args.remove:
        for item in args.add or []:
            if item in PRESETS_BY_ID:
                if item not in news["feeds"]:
                    news["feeds"].append(item)
                _out(f"added {PRESETS_BY_ID[item].name}")
            elif item.lower().startswith(("http://", "https://")):
                from .feeds import fetch_feed

                try:
                    title, items = fetch_feed(item)
                except Exception as e:
                    _out(f"couldn't read {item}: {e}")
                    return 1
                news["custom"] = [f for f in news["custom"] if f["url"] != item]
                news["custom"].append({"name": (args.name or title or item)[:40], "url": item, "enabled": True})
                _out(f"added {args.name or title or item} ({len(items)} items)")
            else:
                _out(f"{item!r} is neither a built-in feed id nor an http(s) URL")
                return 1
        for item in args.remove or []:
            news["feeds"] = [f for f in news["feeds"] if f != item]
            news["custom"] = [f for f in news["custom"] if f["url"] != item and f.get("name") != item]
            _out(f"removed {item}")
        return _saved(cfg, "feeds updated; fetch now with: hothello refresh --news")
    _out("News feeds (change with: hothello feeds --add ID|URL --remove ID|URL)\n")
    group = None
    for p in PRESETS:
        if p.group != group:
            group = p.group
            _out(f"  {group}")
        _out(f"   [{'x' if p.id in news['feeds'] else ' '}] {p.id:<17} {p.name}")
    if news["custom"]:
        _out("  Yours")
        for f in news["custom"]:
            _out(f"   [{'x' if f.get('enabled', True) else ' '}] {f['name']:<17} {f['url']}")
    return 0


def cmd_headlines(args) -> int:
    cfg = config.load()
    news = cfg["news"]
    changed = []
    for attr, key in (("count", "count"), ("per_source", "per_source"), ("max_age", "max_age_hours")):
        value = getattr(args, attr)
        if value is not None:
            news[key] = value
            changed.append(f"{key.replace('_', ' ')}: {value}")
    if changed:
        return _saved(cfg, "\n".join(changed))
    _out(f"headlines: {'on' if news['enabled'] else 'off'} · {news['count']} shown · at most "
         f"{news['per_source']} per source · hidden after {news['max_age_hours']}h · refreshed every "
         f"{news['refresh_minutes']} min")
    _out("  change with: hothello headlines --count N --per-source N --max-age HOURS ·  hothello off headlines")
    return 0


# -- animation ------------------------------------------------------------------------------------------

def cmd_animation(args) -> int:
    cfg = config.load()
    anim = cfg["animation"]
    changed = []
    if args.style:
        key = _pick(args.style, ANIMATIONS, "animation")
        if key is None:
            return 1
        if args.try_it:
            return play_now(cfg, key, args.speed or anim["speed"], args.target or anim["target"])
        anim["style"] = key
        changed.append(f"animation: {key} ({ANIMATIONS[key]})")
    if args.speed:
        anim["speed"] = args.speed
        changed.append(f"speed: {args.speed}")
    if args.target:
        anim["target"] = args.target
        changed.append(f"animates: {'the art only' if args.target == 'art' else 'everything'}")
    if changed:
        config.save(cfg)
        _out("\n".join(changed))
        if args.try_it:
            return play_now(cfg, anim["style"], anim["speed"], anim["target"])
        _out("  (watch it with: hothello preview)")
        return 0
    if args.try_it:
        return play_now(cfg, anim["style"], anim["speed"], anim["target"])
    _out("Login animations (set with: hothello animation STYLE; try one without saving: --try)\n")
    for key, text in ANIMATIONS.items():
        _out(f" {_mark(key == anim['style'])} {key:<8} {text}")
    _out(f"\n  speed: {anim['speed']} ({' / '.join(SPEEDS)})  ·  animates: {anim['target']} (all / art)")
    _out("  any key skips an animation; it never runs when output isn't a terminal")
    return 0


def play_now(cfg: dict, style: str, speed: str, target: str) -> int:
    from . import animate, motd, term
    from .store import Store

    term.enable_vt()
    measured = term.measure()
    if not measured or not sys.stdout.isatty():
        _out("animations need a terminal")
        return 1
    res = motd.build(cfg, Store(), dry_run=True, measured=measured)
    animate.play(res.text, style=style, speed=speed, width=res.plan.usable, term_rows=measured[1],
                 painter=themes.Painter(res.color), ascii_only=res.glyphs == "ascii",
                 only=res.sections.get("art") if target == "art" else None, focus=res.sections.get("art"))
    return 0


# -- generic get / set / reset ---------------------------------------------------------------------------

def _walk(cfg: dict, key: str):
    node = cfg
    parts = key.split(".")
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            raise KeyError(key)
        node = node[part]
    if not isinstance(node, dict) or parts[-1] not in node:
        raise KeyError(key)
    return node, parts[-1]


def cmd_get(args) -> int:
    cfg = config.load()
    if not args.key:
        _out(json.dumps(cfg, indent=2))
        return 0
    try:
        node, leaf = _walk(cfg, args.key)
    except KeyError:
        _out(f"no setting called {args.key!r}; see: hothello get")
        return 1
    _out(json.dumps(node[leaf], indent=2))
    return 0


def cmd_set(args) -> int:
    cfg = config.load()
    try:
        node, leaf = _walk(cfg, args.key)
    except KeyError:
        _out(f"no setting called {args.key!r}; see: hothello get")
        return 1
    raw = " ".join(args.value)
    try:
        value = json.loads(raw)
    except ValueError:
        value = raw
    old = node[leaf]
    if isinstance(old, bool) and isinstance(value, str) and value.lower() in ("on", "off", "yes", "no"):
        value = value.lower() in ("on", "yes")
    if old is not None and type(old) is not type(value) and not (isinstance(old, (int, float)) and isinstance(value, (int, float))):
        _out(f"{args.key} should be {type(old).__name__}, got {type(value).__name__}: {raw}")
        return 1
    node[leaf] = value
    return _saved(cfg, f"{args.key} = {json.dumps(value)}")


def cmd_reset(args) -> int:
    import copy

    cfg = config.load()
    section = args.section or "all"
    if section != "all" and section not in config.DEFAULTS:
        _out(f"unknown section {section!r}; choose from: all, {', '.join(config.DEFAULTS)}")
        return 1
    if not args.yes:
        _out(f"this resets {'every setting' if section == 'all' else 'the ' + section + ' settings'} "
             "to the defaults; add --yes to confirm")
        return 1
    if section == "all":
        cfg = copy.deepcopy(config.DEFAULTS)
    else:
        cfg[section] = copy.deepcopy(config.DEFAULTS[section])
    return _saved(cfg, f"reset {section} to defaults")


def cmd_greeting(args) -> int:
    cfg = config.load()
    if args.text:
        cfg["theme"]["greeting"] = " ".join(args.text)
        return _saved(cfg, f"greeting: {cfg['theme']['greeting']}")
    _out(f"greeting: {cfg['theme']['greeting']}")
    _out("  fields: {greeting} {user} {host} {os} {date} {time} {weekday}")
    _out(f"  header segments: {', '.join(cfg['theme']['segments'])}  (choices: {', '.join(SEGMENT_CHOICES)})")
    _out("  change with: hothello greeting 'Hi {user}!'   ·   hothello set theme.segments '[\"greeting\", \"datetime\"]'")
    return 0

