"""The five settings tabs."""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from dataclasses import dataclass

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label, Select, SelectionList, Static, Switch, Tree

from .. import hooks, themes
from ..config import CHANGE_MODES, CYCLE_MODES, FRAMES, PREFER_MODES, SIZE_PRESETS
from ..feeds import PRESETS, enabled_feeds, fetch_feed
from ..store import ArtFilter
from ..sysinfo import SEGMENT_CHOICES
from ..sysstat import ITEMS as SYSTEM_ITEMS


def field(label: str, widget: Widget, hint: str | None = None) -> Vertical:
    parts: list[Widget] = [Label(label, classes="field-label"), widget]
    if hint:
        parts.append(Static(hint, classes="hint"))
    return Vertical(*parts, classes="field")


def switch_row(label: str, switch: Switch) -> Horizontal:
    return Horizontal(switch, Label(label, classes="switch-label"), classes="switch-row")


def int_value(event: Input.Changed, lo: int, hi: int) -> int | None:
    try:
        value = int(event.value)
    except ValueError:
        return None
    return value if lo <= value <= hi else None


# -- Art ---------------------------------------------------------------------------------

@dataclass
class Cat:
    id: int
    group: int
    name: str
    count: int
    cached: int


class CategoryTree(Tree):
    """Grouped category list with check boxes.  Space (or Enter / click on a
    category) checks; Space on a group checks or clears the whole group."""

    BINDINGS = [Binding("space", "toggle_check", "Check / uncheck")]

    class Changed(Message):
        pass

    def __init__(self, **kwargs) -> None:
        super().__init__("Categories", **kwargs)
        self.show_root = False
        self.selected: set[int] = set()
        self.groups: list[tuple[int, str]] = []
        self.by_group: dict[int, list[Cat]] = defaultdict(list)

    def load(self, groupings, categories, memberships, selected) -> None:
        self.groups = [(g["id"], g["name"]) for g in groupings]
        cats = {c["id"]: Cat(c["id"], c["grouping_id"], c["name"], c["count"] or 0, c["cached"]) for c in categories}
        memberships = memberships or [(c.id, c.group) for c in cats.values() if c.group is not None]
        self.by_group = defaultdict(list)
        for cid, gid in memberships:
            if cid in cats:
                self.by_group[gid].append(cats[cid])
        for members in self.by_group.values():
            members.sort(key=lambda c: c.name.casefold())
        self.selected = set(selected)

    @property
    def total(self) -> int:
        return len({c.id for members in self.by_group.values() for c in members})

    def rebuild(self, needle: str = "") -> None:
        self.clear()
        n = needle.casefold().strip()
        for gid, gname in self.groups:
            cats = self.by_group.get(gid, [])
            if n and n not in gname.casefold():
                cats = [c for c in cats if n in c.name.casefold()]
            if not cats:
                continue
            node = self.root.add(self._group_label(gid, gname), data=("g", gid, gname), expand=bool(n))
            for c in cats:
                node.add_leaf(self._cat_label(c), data=("c", c))

    def _cat_label(self, c: Cat) -> Text:
        on = c.id in self.selected
        t = Text("[x] " if on else "[ ] ", style="bold green" if on else "dim")
        t.append(c.name, style="bold" if on else "")
        t.append(f"  {c.count}", style="dim")
        if c.cached:
            t.append(f" · {c.cached} cached", style="cyan")
        return t

    def _group_label(self, gid: int, gname: str) -> Text:
        ids = [c.id for c in self.by_group.get(gid, [])]
        n_on = sum(i in self.selected for i in ids)
        mark = "[x] " if ids and n_on == len(ids) else "[-] " if n_on else "[ ] "
        t = Text(mark, style="bold green" if n_on else "dim")
        t.append(gname, style="bold")
        t.append(f"  {n_on}/{len(ids)}", style="dim")
        return t

    def relabel(self) -> None:
        for gnode in self.root.children:
            _, gid, gname = gnode.data
            gnode.set_label(self._group_label(gid, gname))
            for leaf in gnode.children:
                leaf.set_label(self._cat_label(leaf.data[1]))

    def action_toggle_check(self) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        if node.data[0] == "c":
            self.selected ^= {node.data[1].id}
        else:
            ids = {leaf.data[1].id for leaf in node.children}
            if ids <= self.selected:
                self.selected -= ids
            else:
                self.selected |= ids
        self.relabel()
        self.post_message(self.Changed())

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if event.node.data and event.node.data[0] == "c":
            self.action_toggle_check()


class ArtPane(Horizontal):
    def compose(self) -> ComposeResult:
        art = self.app.cfg["art"]
        with Vertical(id="cat-col"):
            yield Input(placeholder="Filter categories: cats, star wars, halloween ...", id="cat-filter")
            yield CategoryTree(id="cat-tree")
            with Horizontal(classes="buttons"):
                yield Button("Check all", id="cat-all")
                yield Button("Clear", id="cat-none")
                yield Button("Expand", id="cat-expand")
                yield Button("Collapse", id="cat-collapse")
            yield Static(id="cat-summary", classes="hint")
        with VerticalScroll(classes="side"):
            yield switch_row("Show ASCII art", Switch(art["enabled"], id="art-enabled"))
            yield field("How to cycle", Select([(v, k) for k, v in CYCLE_MODES.items()],
                                               value=art["cycle"], allow_blank=False, id="art-cycle"))
            yield field("Change the art", Select([(v, k) for k, v in CHANGE_MODES.items()],
                                                 value=art["change"], allow_blank=False, id="art-change"))
            yield field("Size preference", Select([(v, k) for k, v in PREFER_MODES.items()],
                                                  value=art["prefer"], allow_blank=False, id="art-prefer"))
            yield switch_row("Hide pieces flagged for nudity / explicit content",
                             Switch(art["hide_flagged"], id="art-hide-flagged"))
            yield field("Category pages per background fetch",
                        Input(str(art["pages_per_refresh"]), type="integer", id="art-pages", classes="short"),
                        "Each page is 20 random pieces of one category.")
            yield Static(id="art-stats", classes="stats")
            yield Button("Fetch more art now", id="art-fetch", variant="primary")
            yield Button("Reload category list", id="art-catalog")

    def on_mount(self) -> None:
        self.data_changed()
        if not self.app.store.groupings():
            self.query_one("#cat-summary", Static).update("Downloading the category list ...")
            self.app.fetch(catalog=True)

    def data_changed(self) -> None:
        tree = self.query_one(CategoryTree)
        store = self.app.store
        tree.load(store.groupings(), store.categories(), store.category_groupings(), self.app.cfg["art"]["categories"])
        tree.rebuild(self.query_one("#cat-filter", Input).value)
        self.refresh_view()

    def refresh_view(self) -> None:
        cfg, store = self.app.cfg, self.app.store
        selected = cfg["art"]["categories"]
        total = self.query_one(CategoryTree).total
        self.query_one("#cat-summary", Static).update(
            f"{len(selected)} categories checked" if selected
            else f"Nothing checked = every category ({total}). Space/Enter checks, Space on a group checks it all."
        )
        plan = self.app.terminal_plan()
        loose = ArtFilter(categories=selected or None, hide_flagged=cfg["art"]["hide_flagged"])
        fits = plan.art_filter(cfg)
        self.query_one("#art-stats", Static).update(
            f"[b]{store.art_count()}[/b] pieces cached\n"
            f"[b]{store.count(loose)}[/b] in your categories\n"
            f"[b]{store.count(fits)}[/b] fit this {plan.cols}x{plan.rows or 'any'} screen"
            f" (art up to {plan.art_width}x{plan.art_height or 'any'})\n"
            f"[b]{store.count(fits, unseen=True)}[/b] not shown yet"
        )

    @on(Input.Changed, "#cat-filter")
    def _filter(self, event: Input.Changed) -> None:
        self.query_one(CategoryTree).rebuild(event.value)

    @on(CategoryTree.Changed)
    def _checked(self) -> None:
        self.app.cfg["art"]["categories"] = sorted(self.query_one(CategoryTree).selected)
        self.app.save_config()

    @on(Button.Pressed, "#cat-all, #cat-none")
    def _all_none(self, event: Button.Pressed) -> None:
        tree = self.query_one(CategoryTree)
        visible = {leaf.data[1].id for g in tree.root.children for leaf in g.children}
        if event.button.id == "cat-all":
            tree.selected |= visible
        else:
            tree.selected -= visible
        tree.relabel()
        self._checked()

    @on(Button.Pressed, "#cat-expand")
    def _expand(self) -> None:
        self.query_one(CategoryTree).root.expand_all()

    @on(Button.Pressed, "#cat-collapse")
    def _collapse(self) -> None:
        tree = self.query_one(CategoryTree)
        for node in tree.root.children:
            node.collapse()

    @on(Switch.Changed, "#art-enabled, #art-hide-flagged")
    def _switch(self, event: Switch.Changed) -> None:
        key = {"art-enabled": "enabled", "art-hide-flagged": "hide_flagged"}[event.switch.id or ""]
        self.app.cfg["art"][key] = event.value
        self.app.save_config()

    @on(Select.Changed, "#art-cycle, #art-change, #art-prefer")
    def _select(self, event: Select.Changed) -> None:
        self.app.cfg["art"][(event.select.id or "")[4:]] = event.value
        self.app.save_config()

    @on(Input.Changed, "#art-pages")
    def _pages(self, event: Input.Changed) -> None:
        if (v := int_value(event, 1, 10)) is not None:
            self.app.cfg["art"]["pages_per_refresh"] = v
            self.app.save_config()

    @on(Button.Pressed, "#art-fetch")
    def _fetch(self) -> None:
        self.app.fetch(art=True)

    @on(Button.Pressed, "#art-catalog")
    def _catalog(self) -> None:
        self.app.fetch(catalog=True)


# -- Display --------------------------------------------------------------------------------

class DisplayPane(VerticalScroll):
    def compose(self) -> ComposeResult:
        d = self.app.cfg["display"]
        with Horizontal(classes="columns"):
            with Vertical(classes="column"):
                yield field("Screen size", Select([(label, key) for key, (label, _, _) in SIZE_PRESETS.items()],
                                                  value=d["size"], allow_blank=False, id="d-size"),
                            "Everything (header, art, headlines) is fitted into this area.")
                with Horizontal(classes="inline"):
                    yield Label("Custom size", classes="inline-label")
                    yield Input(str(d["width"]), type="integer", id="d-width", classes="short")
                    yield Label("x", classes="inline-x")
                    yield Input(str(d["height"]), type="integer", id="d-height", classes="short")
                yield Static("Used for 'Custom', and when there is no terminal to measure (e.g. update-motd.d).",
                             classes="hint")
                with Horizontal(classes="inline"):
                    yield Label("Smallest art worth showing", classes="inline-label")
                    yield Input(str(d["min_width"]), type="integer", id="d-min_width", classes="short")
                    yield Label("x", classes="inline-x")
                    yield Input(str(d["min_height"]), type="integer", id="d-min_height", classes="short")
                with Horizontal(classes="inline"):
                    yield Label("Rows kept free for the prompt", classes="inline-label")
                    yield Input(str(d["reserve_rows"]), type="integer", id="d-reserve_rows", classes="short")
            with Vertical(classes="column"):
                yield field("Frame around the art", Select([(f, f) for f in FRAMES], value=d["frame"],
                                                           allow_blank=False, id="d-frame"))
                yield field("Alignment", Select([("Centered", "center"), ("Left", "left")], value=d["align"],
                                                allow_blank=False, id="d-align"))
                yield field("When no cached art fits", Select(
                    [("Crop the closest fit", "crop"), ("Skip the art", "skip")],
                    value=d["oversize"], allow_blank=False, id="d-oversize"))
                yield switch_row("Show title and artist credit", Switch(d["credit"], id="d-credit"))
        yield Static(id="size-info", classes="stats")

    def refresh_view(self) -> None:
        plan = self.app.terminal_plan()
        cfg = self.app.cfg
        store = self.app.store
        flt = plan.art_filter(cfg)
        self.query_one("#size-info", Static).update(
            f"This terminal is [b]{self.app.size.width}x{self.app.size.height}[/b].  "
            f"The MOTD uses [b]{plan.cols}x{plan.rows or 'any'}[/b], leaving art up to "
            f"[b]{plan.art_width}x{plan.art_height or 'any'}[/b] with {len(plan.headlines)} headlines.  "
            f"[b]{store.count(flt)}[/b] cached pieces fit.  Press [b]p[/b] to preview."
        )

    def on_mount(self) -> None:
        self.refresh_view()

    def on_resize(self) -> None:
        self.refresh_view()

    @on(Select.Changed)
    def _select(self, event: Select.Changed) -> None:
        self.app.cfg["display"][(event.select.id or "")[2:]] = event.value
        self.app.save_config()

    @on(Switch.Changed, "#d-credit")
    def _credit(self, event: Switch.Changed) -> None:
        self.app.cfg["display"]["credit"] = event.value
        self.app.save_config()

    @on(Input.Changed)
    def _number(self, event: Input.Changed) -> None:
        key = (event.input.id or "")[2:]
        limits = {"width": (20, 1000), "height": (5, 500), "min_width": (1, 400), "min_height": (1, 200),
                  "reserve_rows": (0, 20)}
        if key in limits and (v := int_value(event, *limits[key])) is not None:
            self.app.cfg["display"][key] = v
            self.app.save_config()


# -- News -------------------------------------------------------------------------------------

class NewsPane(Horizontal):
    def compose(self) -> ComposeResult:
        n = self.app.cfg["news"]
        with Vertical(id="presets-col"):
            yield switch_row("Show headlines", Switch(n["enabled"], id="n-enabled"))
            yield Label("Built-in feeds  (Space toggles)", classes="field-label")
            yield SelectionList(*[(f"{p.group:<9}{p.name}", p.id, p.id in n["feeds"]) for p in PRESETS],
                                id="n-presets")
        with VerticalScroll(classes="side wide"):
            yield Label("Your own feeds", classes="field-label")
            yield DataTable(id="n-custom", cursor_type="row", zebra_stripes=True)
            with Horizontal(classes="inline"):
                yield Input(placeholder="Name (optional)", id="n-name", classes="name")
                yield Input(placeholder="https://example.com/feed.xml", id="n-url")
            with Horizontal(classes="buttons"):
                yield Button("Add feed", id="n-add", variant="primary")
                yield Button("On / off", id="n-toggle")
                yield Button("Remove", id="n-remove", variant="error")
            with Horizontal(classes="inline"):
                yield Label("Headlines", classes="inline-label narrow")
                yield Input(str(n["count"]), type="integer", id="n-count", classes="short")
                yield Label("Max per source", classes="inline-label narrow")
                yield Input(str(n["per_source"]), type="integer", id="n-per_source", classes="short")
            with Horizontal(classes="inline"):
                yield Label("Hide older than (h)", classes="inline-label narrow")
                yield Input(str(n["max_age_hours"]), type="integer", id="n-max_age_hours", classes="short")
                yield Label("Refresh every (min)", classes="inline-label narrow")
                yield Input(str(n["refresh_minutes"]), type="integer", id="n-refresh_minutes", classes="short")
            yield field("Clickable links (OSC 8)", Select(
                [("Auto-detect terminal", "auto"), ("Always", "on"), ("Never", "off")],
                value=n["hyperlinks"], allow_blank=False, id="n-hyperlinks"))
            yield switch_row("Show source badge", Switch(n["show_source"], id="n-show_source"))
            yield switch_row("Show age (2h, 1d ...)", Switch(n["show_age"], id="n-show_age"))
            yield Button("Fetch headlines now", id="n-fetch")
            yield Static(id="n-status", classes="stats")

    def on_mount(self) -> None:
        table = self.query_one("#n-custom", DataTable)
        table.add_columns("On", "Name", "URL")
        self.data_changed()

    def data_changed(self) -> None:
        table = self.query_one("#n-custom", DataTable)
        table.clear()
        for feed in self.app.cfg["news"]["custom"]:
            table.add_row("yes" if feed.get("enabled", True) else "no", feed.get("name", ""), feed["url"])
        status = self.app.store.feed_status()
        lines = []
        for f in enabled_feeds(self.app.cfg["news"]):
            s = status.get(f.url)
            if s is None:
                lines.append(f"[dim]-[/dim] {f.name}: not fetched yet")
            elif s["ok"]:
                lines.append(f"[green]ok[/green] {f.name}: {s['items']} items")
            else:
                lines.append(f"[red]!![/red] {f.name}: {s['error']}")
        self.query_one("#n-status", Static).update("\n".join(lines) or "No feeds enabled.")

    def _save(self) -> None:
        self.app.save_config()
        self.data_changed()

    @on(Switch.Changed)
    def _switch(self, event: Switch.Changed) -> None:
        self.app.cfg["news"][(event.switch.id or "")[2:]] = event.value
        self._save()

    @on(SelectionList.SelectedChanged, "#n-presets")
    def _presets(self, event: SelectionList.SelectedChanged) -> None:
        self.app.cfg["news"]["feeds"] = list(event.selection_list.selected)
        self._save()

    @on(Select.Changed, "#n-hyperlinks")
    def _links(self, event: Select.Changed) -> None:
        self.app.cfg["news"]["hyperlinks"] = event.value
        self._save()

    @on(Input.Changed, "#n-count, #n-per_source, #n-max_age_hours, #n-refresh_minutes")
    def _number(self, event: Input.Changed) -> None:
        key = (event.input.id or "")[2:]
        limits = {"count": (0, 30), "per_source": (1, 30), "max_age_hours": (0, 24 * 30), "refresh_minutes": (5, 1440)}
        if (v := int_value(event, *limits[key])) is not None:
            self.app.cfg["news"][key] = v
            self.app.save_config()

    @on(Button.Pressed, "#n-add")
    def _add(self) -> None:
        url = self.query_one("#n-url", Input).value.strip()
        if not url.lower().startswith(("http://", "https://")):
            self.app.notify("Enter the feed's http(s):// URL", severity="error")
            return
        if any(f["url"] == url for f in self.app.cfg["news"]["custom"]):
            self.app.notify("That feed is already in the list", severity="warning")
            return
        self.app.notify(f"Checking {url} ...", timeout=3)
        self._check_feed(url, self.query_one("#n-name", Input).value.strip())

    @work(thread=True, exclusive=True, group="feed-check")
    def _check_feed(self, url: str, name: str) -> None:
        try:
            title, items = fetch_feed(url)
        except Exception as e:
            self.app.call_from_thread(self.app.notify, f"Couldn't read that feed: {e}", severity="error", timeout=8)
            return
        if not items:
            self.app.call_from_thread(self.app.notify, "That URL parsed, but has no items", severity="warning")
            return
        self.app.call_from_thread(self._added, url, name or title or url, len(items))

    def _added(self, url: str, name: str, count: int) -> None:
        self.app.cfg["news"]["custom"].append({"name": name[:40], "url": url, "enabled": True})
        self.query_one("#n-url", Input).value = ""
        self.query_one("#n-name", Input).value = ""
        self._save()
        self.app.notify(f"Added {name} ({count} items). Fetching headlines ...")
        self.app.fetch(news=True)

    def _cursor_feed(self) -> int | None:
        table = self.query_one("#n-custom", DataTable)
        if not self.app.cfg["news"]["custom"] or table.cursor_row is None:
            self.app.notify("Select one of your feeds first", severity="warning")
            return None
        return min(table.cursor_row, len(self.app.cfg["news"]["custom"]) - 1)

    @on(Button.Pressed, "#n-toggle")
    def _toggle(self) -> None:
        if (i := self._cursor_feed()) is not None:
            feed = self.app.cfg["news"]["custom"][i]
            feed["enabled"] = not feed.get("enabled", True)
            self._save()

    @on(Button.Pressed, "#n-remove")
    def _remove(self) -> None:
        if (i := self._cursor_feed()) is not None:
            feed = self.app.cfg["news"]["custom"].pop(i)
            self._save()
            self.app.notify(f"Removed {feed.get('name') or feed['url']}")

    @on(Button.Pressed, "#n-fetch")
    def _fetch(self) -> None:
        self.app.fetch(news=True)


# -- System ------------------------------------------------------------------------------------

class SystemPane(VerticalScroll):
    """The themed replacement for Ubuntu's plain login message."""

    def compose(self) -> ComposeResult:
        s = self.app.cfg["system"]
        yield switch_row("Show a System section: load, disk, memory, users, addresses ...",
                         Switch(s["enabled"], id="s-enabled"))
        with Horizontal(classes="columns"):
            with Vertical(classes="column"):
                yield Label("Facts to show", classes="field-label")
                yield SelectionList(*[(label, key, key in s["items"]) for key, label in SYSTEM_ITEMS.items()],
                                    id="s-items")
            with Vertical(classes="column"):
                yield switch_row("Alerts: pending updates, restart required, new release",
                                 Switch(s["alerts"], id="s-alerts"))
                yield switch_row("Last login (time and address)", Switch(s["last_login"], id="s-last_login"))
                yield switch_row("Usage bars for disk / memory / swap", Switch(s["bars"], id="s-bars"))
        if os.name != "nt":
            yield switch_row("Hide the system's plain login message (~/.hushlogin), so this themed version "
                             "replaces it instead of repeating it", Switch(hooks.hushlogin_enabled(), id="hush"))
        yield Static("Press [b]p[/b] to preview.  On short screens the grid is dropped before the art, "
                     "but alerts such as 'restart required' stay.", classes="hint")

    @on(Switch.Changed, "#s-enabled, #s-alerts, #s-last_login, #s-bars")
    def _switch(self, event: Switch.Changed) -> None:
        self.app.cfg["system"][(event.switch.id or "")[2:]] = event.value
        self.app.save_config()

    @on(SelectionList.SelectedChanged, "#s-items")
    def _items(self, event: SelectionList.SelectedChanged) -> None:
        chosen = set(event.selection_list.selected)
        self.app.cfg["system"]["items"] = [k for k in SYSTEM_ITEMS if k in chosen]
        self.app.save_config()

    @on(Switch.Changed, "#hush")
    def _hush(self, event: Switch.Changed) -> None:
        if event.value != hooks.hushlogin_enabled():
            self.app.notify(hooks.set_hushlogin(event.value))
            if event.value != hooks.hushlogin_enabled():  # e.g. an existing file we don't own
                with event.switch.prevent(Switch.Changed):
                    event.switch.value = hooks.hushlogin_enabled()


# -- Theme --------------------------------------------------------------------------------------

GLYPH_CHOICES = [
    ("Auto-detect", "auto"),
    ("Nerd Font (icons + all separators)", "nerd"),
    ("Powerline font (arrows only)", "powerline"),
    ("Plain Unicode", "unicode"),
    ("ASCII only", "ascii"),
]
COLOR_CHOICES = [
    ("Auto-detect", "auto"), ("24-bit truecolor", "truecolor"), ("256 colours", "256"),
    ("16 colours", "16"), ("No colour", "none"),
]
ART_STYLES = [
    ("Theme default", "theme"), ("Plain", "plain"), ("Solid colour", "solid"),
    ("Gradient", "gradient"), ("Rainbow", "rainbow"),
]


class ThemePane(Horizontal):
    def compose(self) -> ComposeResult:
        t = self.app.cfg["theme"]
        with VerticalScroll(id="theme-left"):
            yield field("Theme", Select(self._theme_options(), value=t["name"] if t["name"] in themes.all_themes()
                                        else themes.DEFAULT_THEME, allow_blank=False, id="t-name"))
            yield field("Glyphs (match your terminal font)", Select(GLYPH_CHOICES, value=t["glyphs"],
                                                                    allow_blank=False, id="t-glyphs"))
            yield field("Colour depth", Select(COLOR_CHOICES, value=t["color"], allow_blank=False, id="t-color"))
            yield field("Art colouring", Select(ART_STYLES, value=t["art_style"], allow_blank=False, id="t-art_style"))
            yield Label("Header segments", classes="field-label")
            yield SelectionList(*[(label, key, key in t["segments"]) for key, label in SEGMENT_CHOICES.items()],
                                id="t-segments")
            yield field("Greeting", Input(t["greeting"], id="t-greeting"),
                        "{greeting} {user} {host} {os} {date} {time} {weekday}")
            yield field("Date format", Input(t["date_format"], id="t-date_format"), "strftime codes, e.g. %a %d %b %H:%M")
            yield field("Timezone", Input(t["timezone"], placeholder="machine default", id="t-timezone"),
                        "IANA name such as America/Chicago or Europe/London")
            yield Label("Import an oh-my-posh theme", classes="field-label")
            with Horizontal(classes="inline"):
                yield Input(themes.detect_omp_config() or "", placeholder="theme name or path to .omp.json",
                            id="t-omp")
                yield Button("Import", id="t-import")
        with Vertical(id="theme-right"):
            yield Static(id="theme-preview")
            yield Static("[b]n[/b] next art   [b]p[/b] full-screen preview", classes="hint")

    @staticmethod
    def _theme_options() -> list[tuple[str, str]]:
        return [(f"{t.name}" + ("" if t.source == "built-in" else "  (yours)"), key)
                for key, t in themes.all_themes().items()]

    def on_mount(self) -> None:
        self.refresh_view()

    def on_resize(self) -> None:
        self.refresh_view()

    def refresh_view(self) -> None:
        box = self.query_one("#theme-preview", Static)
        width = max(box.size.width, 40)
        height = max(box.size.height, 12)
        text, _ = self.app.render_motd(width, height)
        box.update(text)

    @on(Select.Changed)
    def _select(self, event: Select.Changed) -> None:
        self.app.cfg["theme"][(event.select.id or "")[2:]] = event.value
        self.app.save_config()

    @on(SelectionList.SelectedChanged, "#t-segments")
    def _segments(self, event: SelectionList.SelectedChanged) -> None:
        chosen = set(event.selection_list.selected)
        self.app.cfg["theme"]["segments"] = [k for k in SEGMENT_CHOICES if k in chosen]
        self.app.save_config()

    @on(Input.Changed, "#t-greeting, #t-date_format, #t-timezone")
    def _text(self, event: Input.Changed) -> None:
        self.app.cfg["theme"][(event.input.id or "")[2:]] = event.value
        self.app.save_config()

    @on(Button.Pressed, "#t-import")
    def _import(self) -> None:
        source = self.query_one("#t-omp", Input).value.strip()
        if not source:
            self.app.notify("Enter an oh-my-posh theme name (e.g. takuya) or a config path", severity="error")
            return
        self._do_import(source)

    @work(thread=True, exclusive=True, group="omp")
    def _do_import(self, source: str) -> None:
        try:
            theme = themes.import_omp(source)
        except Exception as e:
            self.app.call_from_thread(self.app.notify, f"Import failed: {e}", severity="error", timeout=10)
            return
        self.app.call_from_thread(self._imported, theme)

    def _imported(self, theme: themes.Theme) -> None:
        select = self.query_one("#t-name", Select)
        select.set_options(self._theme_options())
        select.value = theme.key  # fires Select.Changed, which saves
        self.app.notify(f"Imported {theme.name}")


# -- Install --------------------------------------------------------------------------------------

class InstallPane(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Static(
            "motd+ runs [b]motdplus show[/b] from your shell's startup file, so a new piece of art "
            "(and the headlines) greets every interactive login.  New art and news are fetched in the "
            "background, so logging in never waits on the network.",
            classes="intro",
        )
        for key, target in hooks.relevant_targets().items():
            with Horizontal(classes="hook-row"):
                yield Label(target.label, classes="hook-label")
                yield Label("", id=f"hs-{key}", classes="hook-state")
                yield Button("Install", id=f"hi-{key}", variant="primary")
                yield Button("Remove", id=f"hr-{key}")
        yield Static(id="install-info", classes="stats")

    def on_mount(self) -> None:
        self.refresh_view()

    def refresh_view(self) -> None:
        is_root = os.name != "nt" and os.geteuid() == 0  # type: ignore[attr-defined]
        for key, target in hooks.relevant_targets().items():
            installed = hooks.is_installed(target)
            state = self.query_one(f"#hs-{key}", Label)
            state.update("[green]installed[/green]" if installed else "[dim]not installed[/dim]")
            self.query_one(f"#hi-{key}", Button).display = not installed and (not target.system or is_root)
            self.query_one(f"#hr-{key}", Button).display = installed and (not target.system or is_root)
        lines = [f"Hook runs: [b]{sys.executable} -m motdplus show[/b]"]
        if "update-motd" in hooks.targets() and not is_root:
            lines.append(
                "System-wide MOTD for every user (needs root):\n"
                f"  sudo {sys.executable} -m motdplus install --target update-motd"
            )
        lines.append("Other commands:  motdplus preview · motdplus refresh · motdplus status · motdplus uninstall")
        self.query_one("#install-info", Static).update("\n\n".join(lines))

    @on(Button.Pressed)
    def _hook(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if not bid.startswith(("hi-", "hr-")):
            return
        target = hooks.targets()[bid[3:]]
        try:
            msg = hooks.install(target) if bid.startswith("hi-") else hooks.uninstall(target)
            self.app.notify(msg)
        except OSError as e:
            self.app.notify(f"{target.label}: {e}", severity="error")
        self.refresh_view()

