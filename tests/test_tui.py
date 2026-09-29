import asyncio

import pytest
from conftest import make_art

pytest.importorskip("textual")

from textual.widgets import Input, Select, Switch, TabbedContent  # noqa: E402

from motdplus import config  # noqa: E402
from motdplus.tui.app import MotdPlusApp, PreviewScreen  # noqa: E402
from motdplus.tui.panes import CategoryTree  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def test_settings_round_trip(store):
    store.upsert_art([make_art(1, 20, 6, categories=[(1, "Cats")]), make_art(2, 20, 6, categories=[(3, "Cars")])])

    async def scenario():
        app = MotdPlusApp()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause()
            tree = app.query_one(CategoryTree)
            assert tree.total == 3  # Cats is listed under two groups but counted once

            # check the first group ("Animals": Cats + Dogs) with space
            tree.focus()
            tree.cursor_line = 0
            await pilot.press("space")
            await pilot.pause()
            assert config.load()["art"]["categories"] == [1, 2]

            # typing letters that are also app bindings goes into the input
            app.query_one("#cat-filter", Input).focus()
            await pilot.press("c", "a", "r", "p", "q")
            await pilot.pause()
            assert app.query_one("#cat-filter", Input).value == "carpq"
            assert not isinstance(app.screen, PreviewScreen)

            app.query_one("#art-hide-flagged", Switch).toggle()
            await pilot.pause()
            assert config.load()["art"]["hide_flagged"] is False

            app.query_one(TabbedContent).active = "tab-display"
            await pilot.pause()
            app.query_one("#d-size", Select).value = "tiny"
            await pilot.pause()
            assert config.load()["display"]["size"] == "tiny"

            app.query_one(TabbedContent).active = "tab-theme"
            await pilot.pause()
            app.query_one("#t-name", Select).value = "gruvbox"
            await pilot.pause()
            assert config.load()["theme"]["name"] == "gruvbox"

            app.query_one(TabbedContent).active = "tab-art"
            await pilot.pause()
            app.set_focus(None)
            await pilot.press("p")
            await pilot.pause()
            assert isinstance(app.screen, PreviewScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, PreviewScreen)

    run(scenario())
