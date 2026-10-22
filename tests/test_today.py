"""Today's look: build, next, wear (once a day), what's left out, none; the endpoints; slugs; collage."""

import uuid
from datetime import date

import pytest
from PIL import Image

from wardrobe import collage, config, db, today

DAY = "2026-10-21"
DRY = {"temp_low": 12, "temp_high": 16, "temp": 14, "rain": False, "condition": "cloudy", "source": "forecast"}


def weather(_day):
    return DRY


@pytest.fixture
def sam(client):
    r = client.post("/api/profiles", json={"name": "Sam"})
    return r.json()


def add(conn, pid, name, category, sub="", color="#1f2a44", status="active", photo=False, **kw):
    gid = db.insert(conn, "garments", {"profile_id": pid, "name": name, "category": category, "subcategory": sub,
                                       "colors": [color], "formality": 2, "warmth": 2, "status": status} | kw)
    if photo:
        fn = f"{uuid.uuid4().hex}.jpg"
        config.THUMB_DIR.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (360, 480), (40, 60, 120)).save(config.THUMB_DIR / fn, "JPEG")
        db.insert(conn, "photos", {"garment_id": gid, "filename": fn, "kind": "item", "is_primary": 1})
    return gid


def wardrobe(conn, pid, photo=False):
    ids = {
        "tee": add(conn, pid, "Navy tee", "top", "t-shirt", photo=photo),
        "shirt": add(conn, pid, "White shirt", "top", "shirt", "#f5f5f5", photo=photo),
        "chinos": add(conn, pid, "Grey chinos", "bottom", "chinos", "#808080", photo=photo),
        "jeans": add(conn, pid, "Blue jeans", "bottom", "jeans", "#34507a", photo=photo),
        "sneakers": add(conn, pid, "White sneakers", "shoes", "sneakers", "#f5f5f5", photo=photo),
        "jacket": add(conn, pid, "Navy jacket", "outerwear", "jacket", photo=photo),
    }
    return ids


def wears(conn):
    return conn.execute("SELECT garment_id, worn_on FROM wears ORDER BY id").fetchall()


# ------------------------------------------------------------------ build / next / wear

def test_build_next_wear(sam):
    with db.connect() as conn:
        wardrobe(conn, sam["id"])
        row = today.current(conn, sam, DAY, weather)
        assert row["day"] == DAY and row["pick"] == 0 and row["worn"] == 0
        n = len(row["options"])
        assert 2 <= n <= today.COUNT
        assert row["context"]["temp_low"] == 12 and row["context"]["occasion"] == "casual"

        # current() doesn't rebuild an existing row.
        assert today.current(conn, sam, DAY, lambda d: pytest.fail("rebuilt"))["id"] == row["id"]

        for i in range(1, n + 1):
            row = today.next(conn, sam, DAY, weather)
            assert row["pick"] == i % n  # wraps round

        row = today.next(conn, sam, DAY, weather)
        picked = today.picked(row)["ids"]
        row, logged = today.wear(conn, sam, DAY, weather)
        assert logged and row["worn"] == 1
        assert sorted(w[0] for w in wears(conn)) == sorted(picked)
        assert {w[1] for w in wears(conn)} == {DAY}

        # Idempotent per day, also after Another.
        _, logged = today.wear(conn, sam, DAY, weather)
        assert not logged
        today.next(conn, sam, DAY, weather)
        _, logged = today.wear(conn, sam, DAY, weather)
        assert not logged
        assert len(wears(conn)) == len(picked)


def test_refresh_replaces_row_and_keeps_worn(sam):
    with db.connect() as conn:
        wardrobe(conn, sam["id"])
        today.current(conn, sam, DAY, weather)
        today.next(conn, sam, DAY, weather)
        today.wear(conn, sam, DAY, weather)
        wet = DRY | {"rain": True}
        row = today.build(conn, sam, DAY, refresh=True, weather=lambda d: wet)
        assert row["pick"] == 0 and row["worn"] == 1 and row["context"]["rain"] is True
        assert conn.execute("SELECT COUNT(*) FROM daily_looks").fetchone()[0] == 1


def test_drafts_and_laundry_left_out(sam):
    with db.connect() as conn:
        ids = wardrobe(conn, sam["id"])
        draft = add(conn, sam["id"], "New garment", "top", status="draft")
        conn.execute("UPDATE garments SET status = 'laundry' WHERE id = ?", (ids["jeans"],))
        row = today.current(conn, sam, DAY, weather)
        used = {i for o in row["options"] for i in o["ids"]}
        assert draft not in used and ids["jeans"] not in used
        assert ids["chinos"] in used


def test_too_few_garments_gives_none(sam):
    with db.connect() as conn:
        add(conn, sam["id"], "Navy tee", "top")
        add(conn, sam["id"], "White sneakers", "shoes", color="#f5f5f5")
        row = today.current(conn, sam, DAY, weather)
        v = today.view(conn, sam, row)
        assert v["state"] == "none" and v["items"] == [] and v["image"] is None
        assert "bottom" in v["reason"]
        _, logged = today.wear(conn, sam, DAY, weather)
        assert not logged
        assert today.next(conn, sam, DAY, weather)["pick"] == 0


def test_day_without_a_look_is_rebuilt_when_asked(sam):
    with db.connect() as conn:
        add(conn, sam["id"], "Navy tee", "top")
        row = today.current(conn, sam, DAY, weather)
        assert row["options"] == []
        # Clothes added since: the next ask builds the day again, no refresh needed.
        add(conn, sam["id"], "Grey chinos", "bottom", color="#808080")
        add(conn, sam["id"], "White sneakers", "shoes", color="#f5f5f5")
        again = today.current(conn, sam, DAY, weather)
        assert again["id"] == row["id"] and again["options"] and again["pick"] == 0
        assert "none_reason" not in again["context"]
        # A day with a look is kept as it is.
        assert today.current(conn, sam, DAY, lambda d: pytest.fail("rebuilt"))["id"] == row["id"]


def test_no_weather_still_builds(sam):
    with db.connect() as conn:
        wardrobe(conn, sam["id"])
        v = today.view(conn, sam, today.current(conn, sam, DAY, lambda d: None))
        assert v["state"] != "none" and v["weather"] == "" and v["temp_low"] is None


def test_view(sam):
    with db.connect() as conn:
        wardrobe(conn, sam["id"])
        row = today.current(conn, sam, DAY, lambda d: DRY | {"temp_low": 8.4, "temp_high": 13, "rain": True})
        v = today.view(conn, sam, row)
    assert v["entity_id"] == "sensor.wardrobe_today_sam"
    assert v["weather"] == "8–13 °C, rain likely"
    assert v["option"] == f"1 of {v['options']}"
    assert v["state"] == v["summary"] and len(v["state"]) <= 255
    assert v["state"].split(", ")[0] == v["items"][0]["name"]
    assert len(v["reasons"]) <= 3
    assert v["image"] == f"/media/local/wardrobe/look-sam-{DAY}-0.jpg"
    assert v["generated_at"].endswith("+00:00")


def test_summary_is_capped(sam):
    with db.connect() as conn:
        long = "Very long name " * 10
        add(conn, sam["id"], long + "tee", "top")
        add(conn, sam["id"], long + "chinos", "bottom", color="#808080")
        add(conn, sam["id"], long + "sneakers", "shoes", color="#f5f5f5")
        v = today.view(conn, sam, today.current(conn, sam, DAY, weather))
    assert v["state"] != "none" and len(v["state"]) <= 255 and v["state"].endswith("…")


# ------------------------------------------------------------------ endpoints

def test_today_endpoints(client, sam, monkeypatch):
    monkeypatch.setattr(today, "forecast", weather)
    with db.connect() as conn:
        wardrobe(conn, sam["id"])
    r = client.get("/api/today", params={"profile_id": sam["id"]})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["day"] == db.today() and v["pick"] == 0 and v["worn"] is False

    v2 = client.post("/api/today/next", json={"profile_id": sam["id"]}).json()
    assert v2["pick"] == 1 and v2["summary"] != v["summary"]
    assert client.get("/api/today", params={"profile_id": sam["id"]}).json()["pick"] == 1

    w = client.post("/api/today/wear", json={"profile_id": sam["id"]}).json()
    assert w["worn"] is True
    client.post("/api/today/wear", json={"profile_id": sam["id"]})
    with db.connect() as conn:
        assert len(wears(conn)) == len(w["items"])


def test_today_endpoint_errors(client):
    assert client.get("/api/today").status_code == 400
    assert client.get("/api/today", params={"profile_id": 999}).status_code == 404
    assert client.post("/api/today/next", json={"profile_id": "x"}).status_code == 400


# ------------------------------------------------------------------ slugs and lookup

@pytest.mark.parametrize("name, slug", [
    ("Alex", "alex"), ("Anna B.", "anna_b"), ("Zoë Ångström", "zoe_angstrom"),
    ("  Kim--Lee  ", "kim_lee"), ("José María", "jose_maria"),
])
def test_slug(name, slug):
    assert today.slug(name) == slug


def test_slug_without_ascii_letters():
    assert today.slug("美咲", 7) == "profile_7"


def test_find_profile(client):
    a = client.post("/api/profiles", json={"name": "Anna B."}).json()
    with db.connect() as conn:
        for ref in (a["id"], str(a["id"]), "anna_b", "Anna B.", "ANNA B.", " anna_b "):
            assert today.find_profile(conn, ref)["id"] == a["id"], ref
        assert today.find_profile(conn, "nobody") is None
        assert today.find_profile(conn, None) is None


# ------------------------------------------------------------------ collage

def test_collage_writes_up_to_four_tiles(sam):
    with db.connect() as conn:
        ids = wardrobe(conn, sam["id"], photo=True)
        knit = add(conn, sam["id"], "Grey sweater", "knitwear", "sweater", "#808080", photo=True)
        items = [{"id": i, "category": c, "photo": p} for i, c, p in conn.execute(
            "SELECT g.id, g.category, p.filename FROM garments g JOIN photos p ON p.garment_id = g.id "
            "WHERE g.id IN (?, ?, ?, ?, ?)", (ids["jacket"], knit, ids["tee"], ids["chinos"], ids["sneakers"]))]
    tiles = collage.pick_tiles(items)
    assert len(tiles) == 4
    assert [t["category"] for t in tiles][-2:] == ["bottom", "shoes"]
    assert {t["category"] for t in tiles[:2]} <= {"top", "knitwear", "outerwear"}

    name = f"look-sam-{DAY}-0.jpg"
    assert collage.make(items, name)
    path = config.HA_MEDIA_DIR / name
    with Image.open(path) as im:
        assert im.format == "JPEG" and im.size == (1080, 1080)
        assert im.getpixel((5, 5)) == pytest.approx(collage.BACKGROUND, abs=3)
    # Exists already: left alone.
    mtime = path.stat().st_mtime_ns
    assert collage.make(items, name) and path.stat().st_mtime_ns == mtime


def test_collage_without_photos():
    assert not collage.make([{"id": 1, "category": "top", "photo": None}], "look-x-2026-10-21-0.jpg")


def test_collage_cleanup(data_dir):
    folder = config.HA_MEDIA_DIR
    folder.mkdir(parents=True)
    names = ["look-sam-2026-10-18-0.jpg", "look-sam-2026-10-19-3.jpg", "look-anna_b-2026-10-20-0.jpg",
             "look-sam-2026-10-21-1.jpg", "other.jpg"]
    for n in names:
        (folder / n).write_bytes(b"x")
    # More than two days old goes; two days old stays.
    assert collage.cleanup(date(2026, 10, 21)) == 1
    assert sorted(p.name for p in folder.iterdir()) == sorted(names[1:])
