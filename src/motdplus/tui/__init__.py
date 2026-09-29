"""Textual settings UI (`motdplus` with no arguments)."""


def run() -> int:
    from .app import MotdPlusApp

    MotdPlusApp().run()
    return 0
