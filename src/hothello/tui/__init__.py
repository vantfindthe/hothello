"""Textual settings UI (`hothello` with no arguments)."""


def run() -> int:
    from .app import HothelloApp

    HothelloApp().run()
    return 0
