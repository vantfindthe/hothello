"""The settings app: tabs for art, display, news, theme and install, plus a
full-screen preview that renders exactly what the next login will show."""

from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from .. import config, motd, refresh
from ..store import Store
from .panes import ArtPane, DisplayPane, InstallPane, NewsPane, SystemPane, ThemePane


class PreviewScreen(ModalScreen):
    """The MOTD at this terminal's real size, as the login hook would print it."""

    BINDINGS = [
        Binding("escape,q,p", "dismiss", "Close"),
        Binding("n", "next_art", "Next art"),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="preview-full"):
            yield Static(id="preview-full-text")
        yield Footer()

    def on_mount(self) -> None:
        self.draw()

    def on_resize(self) -> None:
        self.draw()

    def draw(self) -> None:
        text, res = self.app.render_motd(self.app.size.width, self.app.size.height)
        self.query_one("#preview-full-text", Static).update(text)
        self.sub_title = f"{res.plan.cols}x{res.plan.rows or 'any'}"

    def action_next_art(self) -> None:
        self.app.preview_art_id = None
        self.draw()


class MotdPlusApp(App):
    TITLE = "motd+"
    SUB_TITLE = "your login greeting"
    CSS_PATH = "app.tcss"
    BINDINGS = [
        Binding("p", "preview", "Preview"),
        Binding("n", "next_art", "Next art"),
        Binding("a", "play", "Play animation"),
        Binding("f", "fetch", "Fetch art + news"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.cfg = config.load()
        self.store = Store()
        self.preview_art_id: int | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="tab-art"):
            with TabPane("Art", id="tab-art"):
                yield ArtPane()
            with TabPane("Display", id="tab-display"):
                yield DisplayPane()
            with TabPane("News", id="tab-news"):
                yield NewsPane()
            with TabPane("System", id="tab-system"):
                yield SystemPane()
            with TabPane("Theme", id="tab-theme"):
                yield ThemePane()
            with TabPane("Install", id="tab-install"):
                yield InstallPane()
        yield Footer()

    # -- shared helpers used by the panes --------------------------------------

    def save_config(self) -> None:
        # Widgets announce their initial values while mounting; only write real changes.
        if self.cfg != config.load():
            config.save(self.cfg)
        self.settings_changed()

    def settings_changed(self) -> None:
        for pane in self.query("ArtPane, DisplayPane, ThemePane"):
            pane.refresh_view()  # type: ignore[attr-defined]

    def render_motd(self, width: int, height: int) -> tuple[Text, motd.Result]:
        color = self.cfg["theme"].get("color", "auto")
        res = motd.build(
            self.cfg, self.store, measured=(width, height), dry_run=True, prefer_id=self.preview_art_id,
            hyperlinks=False, color="truecolor" if color == "auto" else color,
        )
        if res.pick.art is not None:
            self.preview_art_id = res.pick.art.id
        return Text.from_ansi(res.text.rstrip("\n")), res

    def terminal_plan(self) -> motd.Plan:
        return motd.plan(self.cfg, self.store, measured=(self.size.width, self.size.height))

    # -- actions ----------------------------------------------------------------

    def action_preview(self) -> None:
        self.push_screen(PreviewScreen())

    def action_next_art(self) -> None:
        self.preview_art_id = None
        self.settings_changed()

    def action_play(self) -> None:
        """Leave the UI for a moment and play the login animation full-screen."""
        import sys

        from .. import animate, term, themes

        style = self.cfg["animation"]["style"]
        if style == "none":
            self.notify("Pick an animation first (Display tab, or: motdplus animation STYLE)", severity="warning")
            return
        color = self.cfg["theme"].get("color", "auto")
        res = motd.build(self.cfg, self.store, measured=(self.size.width, self.size.height), dry_run=True,
                         prefer_id=self.preview_art_id, color=term.detect_color() if color == "auto" else color)
        try:
            with self.suspend():
                sys.stdout.write("\x1b[2J\x1b[H")
                animate.play(res.text, style=style, speed=self.cfg["animation"]["speed"], width=res.plan.usable,
                             term_rows=self.size.height, painter=themes.Painter(res.color),
                             ascii_only=res.glyphs == "ascii", focus=res.sections.get("art"),
                             only=res.sections.get("art") if self.cfg["animation"]["target"] == "art" else None)
                try:
                    input("\npress Enter to return ")
                except EOFError:
                    pass
        except Exception as e:  # e.g. SuspendNotSupported when not in a real terminal
            self.notify(f"Can't play here: {e}", severity="warning")

    def action_fetch(self) -> None:
        self.fetch(art=True, news=True)

    @work(thread=True, exclusive=True, group="fetch")
    def fetch(self, *, art: bool = False, news: bool = False, catalog: bool = False) -> None:
        """Network refresh in a worker thread (with its own database connection)."""
        self.call_from_thread(self.notify, "Fetching...", timeout=3)
        messages: list[str] = []
        store = Store()
        try:
            with refresh.Lock() as got:
                if not got:
                    self.call_from_thread(self.notify, "A background refresh is already running", severity="warning")
                    return
                if catalog or (art and refresh.catalog_due(store, 0)):
                    refresh.refresh_catalog(store, messages.append)
                if art:
                    refresh.refresh_art(self.cfg, store, messages.append)
                if news:
                    refresh.refresh_news(self.cfg, store, messages.append)
        except Exception as e:  # show any failure instead of crashing the UI
            messages.append(f"error: {e}")
        finally:
            store.close()
        self.call_from_thread(self._fetched, messages)

    def _fetched(self, messages: list[str]) -> None:
        errors = [m for m in messages if "error" in m.lower() or "HTTP" in m]
        summary = "\n".join(messages[-8:]) or "nothing to fetch"
        self.notify(summary, title="Fetch finished", severity="warning" if errors else "information", timeout=8)
        for pane in self.query("ArtPane, NewsPane"):
            pane.data_changed()  # type: ignore[attr-defined]
        self.settings_changed()
