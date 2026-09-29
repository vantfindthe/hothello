import time

from conftest import make_art

from motdplus.picker import crop, pick


def add(store, *pieces):
    store.upsert_art(list(pieces))


def test_only_fitting_art_is_picked(store, cfg):
    add(store, make_art(1, 10, 5), make_art(2, 200, 5), make_art(3, 10, 80))
    for _ in range(10):
        p = pick(store, cfg["art"], cfg["display"], max_width=50, max_height=20)
        assert p.art.id == 1


def test_shuffle_never_repeats_until_exhausted(store, cfg):
    add(store, *[make_art(i, 10, 5) for i in range(1, 7)])
    first_round = [pick(store, cfg["art"], cfg["display"], max_width=50, max_height=20).art.id for _ in range(6)]
    assert sorted(first_round) == [1, 2, 3, 4, 5, 6]
    # the seventh pick starts a new round instead of failing
    assert pick(store, cfg["art"], cfg["display"], max_width=50, max_height=20).art is not None


def test_dry_run_records_nothing(store, cfg):
    add(store, make_art(1, 10, 5))
    for _ in range(3):
        pick(store, cfg["art"], cfg["display"], max_width=50, max_height=20, dry_run=True)
    assert store.count(__import__("motdplus.store").store.ArtFilter(), unseen=True) == 1
    assert store.kv_get("current") is None


def test_categories_filter(store, cfg):
    add(store, make_art(1, 10, 5, categories=[(1, "Cats")]), make_art(2, 10, 5, categories=[(3, "Cars")]))
    cfg["art"]["categories"] = [3]
    assert {pick(store, cfg["art"], cfg["display"], max_width=50, max_height=20).art.id for _ in range(5)} == {2}


def test_flagged_hidden_by_default(store, cfg):
    add(store, make_art(1, 10, 5, flagged=True), make_art(2, 10, 5))
    assert {pick(store, cfg["art"], cfg["display"], max_width=50, max_height=20).art.id for _ in range(5)} == {2}
    cfg["art"]["hide_flagged"] = False
    store.db.execute("DELETE FROM shown")
    seen = {pick(store, cfg["art"], cfg["display"], max_width=50, max_height=20).art.id for _ in range(2)}
    assert seen == {1, 2}


def test_rotate_walks_categories(store, cfg):
    add(store, make_art(1, 10, 5, categories=[(1, "Cats")]), make_art(2, 10, 5, categories=[(2, "Dogs")]),
        make_art(3, 10, 5, categories=[(3, "Cars")]))
    cfg["art"]["cycle"] = "rotate"
    cfg["art"]["categories"] = [1, 2, 3]
    ids = [pick(store, cfg["art"], cfg["display"], max_width=50, max_height=20).art.id for _ in range(3)]
    assert ids == [1, 2, 3]


def test_daily_change_keeps_the_same_piece(store, cfg):
    add(store, *[make_art(i, 10, 5) for i in range(1, 6)])
    cfg["art"]["change"] = "daily"
    now = time.time()
    first = pick(store, cfg["art"], cfg["display"], max_width=50, max_height=20, now=now).art.id
    again = pick(store, cfg["art"], cfg["display"], max_width=50, max_height=20, now=now + 60).art.id
    later = pick(store, cfg["art"], cfg["display"], max_width=50, max_height=20, now=now + 3 * 86400).art.id
    assert first == again
    assert later != first


def test_crop_fallback_when_nothing_fits(store, cfg):
    add(store, make_art(1, 100, 40))
    p = pick(store, cfg["art"], cfg["display"], max_width=30, max_height=10)
    assert p.art.id == 1 and p.cropped
    assert len(p.lines) == 10 and max(len(line) for line in p.lines) <= 30
    cfg["display"]["oversize"] = "skip"
    assert pick(store, cfg["art"], cfg["display"], max_width=30, max_height=10).art is None


def test_no_room_means_no_art(store, cfg):
    add(store, make_art(1, 5, 1))
    assert pick(store, cfg["art"], cfg["display"], max_width=50, max_height=1).art is None


def test_prefer_large_favours_big_pieces(store, cfg):
    add(store, make_art(1, 10, 4), make_art(2, 60, 20))
    cfg["art"]["prefer"] = "large"
    cfg["art"]["cycle"] = "random"
    ids = [pick(store, cfg["art"], cfg["display"], max_width=80, max_height=30).art.id for _ in range(60)]
    assert ids.count(2) > ids.count(1) * 5


def test_crop_centres():
    lines = ["abcdefgh", "ijklmnop", "qrstuvwx", "yz012345"]
    assert crop(lines, 4, 2) == ["klmn", "stuv"]  # rows 1-2, columns 2-5
