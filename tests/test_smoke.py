"""The app imports, sets up an empty database, and stores a profile and a garment."""

import sqlite3

from wardrobe import config, db


def test_init_on_empty_folder(data_dir):
    assert not config.DB_PATH.exists()
    db.init()
    conn = sqlite3.connect(config.DB_PATH)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    finally:
        conn.close()
    assert config.MEDIA_DIR.is_dir() and config.THUMB_DIR.is_dir()


def test_meta(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    data = r.json()
    assert data["version"] == config.VERSION
    assert data["profiles"] == []
    # No SUPERVISOR_TOKEN: the app starts (lifespan included) without the Home Assistant bridge.
    assert data["running_in_ha"] is False and data["ha_bridge"]["enabled"] is False


def test_profile_and_garment(client, profile):
    assert profile["name"] == "Alex"

    r = client.post("/api/garments", json={"profile_id": profile["id"], "name": "Grey tee",
                                           "category": "top", "material": "100% cotton"})
    assert r.status_code == 201, r.text
    garment = r.json()
    assert garment["name"] == "Grey tee"
    assert garment["status"] == "active"
    assert garment["care"].get("wash"), "default care should be filled in"

    r = client.get("/api/garments", params={"profile_id": profile["id"]})
    assert r.status_code == 200
    assert [g["id"] for g in r.json()] == [garment["id"]]


def test_garment_needs_name(client, profile):
    r = client.post("/api/garments", json={"profile_id": profile["id"], "category": "top"})
    assert r.status_code == 400
