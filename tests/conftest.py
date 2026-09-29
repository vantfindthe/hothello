import pytest

from motdplus import config
from motdplus.store import Art, Store


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own config/cache directory and a plain environment."""
    monkeypatch.setenv("MOTDPLUS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    for var in ("NO_COLOR", "COLORTERM", "WT_SESSION", "TERM_PROGRAM", "POSH_THEME", "MOTDPLUS_SHOWN"):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / "user").mkdir()
    return tmp_path


@pytest.fixture
def cfg():
    return config.load()


def make_art(art_id: int, width: int, height: int, categories=((1, "Cats"),), flagged=False, title=None) -> Art:
    line = ("#" * width)
    return Art(
        id=art_id, title=title or f"Piece {art_id}", artist="tester", width=width, height=height,
        flagged=flagged, text="\n".join([line] * height), categories=list(categories),
    )


@pytest.fixture
def store():
    s = Store()
    s.replace_catalog(
        [(1, "Animals", 10), (2, "Things", 10)],
        [(1, 1, "Cats", 5), (2, 1, "Dogs", 5), (3, 2, "Cars", 5), (1, 2, "Cats", 5)],
    )
    yield s
    s.close()
