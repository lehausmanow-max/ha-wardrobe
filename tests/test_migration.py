"""Migration v2: a populated 0.3.0 database (user_version 1) upgrades with all its data intact."""

import json
import sqlite3

from wardrobe import config, db


def make_v1(path):
    conn = sqlite3.connect(path)
    conn.executescript(db.MIGRATIONS[0])
    conn.execute("PRAGMA user_version = 1")
    conn.execute("INSERT INTO profiles (id, name, ha_user, measurements) VALUES (1, 'Sam', 'sam', ?)",
                 (json.dumps({"chest": 98}),))
    conn.execute("INSERT INTO profiles (id, name) VALUES (2, 'Robin')")
    garments = [
        (1, 1, "Navy crewneck", "top", "active", json.dumps(["#1f2a44"])),
        (2, 1, "Grey chinos", "bottom", "laundry", json.dumps(["#808080"])),
        (3, 2, "White sneakers", "shoes", "active", json.dumps(["#f5f5f5"])),
        (4, 1, "New garment", "top", "draft", "[]"),
    ]
    conn.executemany("INSERT INTO garments (id, profile_id, name, category, status, colors) VALUES (?, ?, ?, ?, ?, ?)",
                     garments)
    conn.executemany("INSERT INTO photos (garment_id, filename, kind, is_primary) VALUES (?, ?, ?, ?)",
                     [(1, "a" * 32 + ".jpg", "item", 1), (1, "b" * 32 + ".jpg", "label", 0),
                      (4, "c" * 32 + ".jpg", "item", 1)])
    conn.executemany("INSERT INTO wears (garment_id, worn_on) VALUES (?, ?)",
                     [(1, "2026-10-01"), (1, "2026-10-08"), (3, "2026-10-02")])
    conn.execute("INSERT INTO looks (id, profile_id, name, rating) VALUES (1, 1, 'Friday', 4)")
    conn.execute("INSERT INTO look_items (look_id, garment_id) VALUES (1, 1), (1, 2)")
    conn.commit()
    conn.close()


def dump(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY rowid")]
                for t in ("profiles", "garments", "photos", "wears", "looks", "look_items")}
    finally:
        conn.close()


def test_v1_database_upgrades_intact(data_dir):
    config.ensure_dirs()
    make_v1(config.DB_PATH)
    before = dump(config.DB_PATH)

    db.init()

    conn = sqlite3.connect(config.DB_PATH)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2 == len(db.MIGRATIONS)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "daily_looks" in tables
    finally:
        conn.close()

    after = dump(config.DB_PATH)
    for table, rows in before.items():
        assert len(after[table]) == len(rows), table
    for old, new in zip(before["profiles"], after["profiles"]):
        assert {k: new[k] for k in old} == old
        assert new["ha_user_id"] == "" and new["settings"] == "{}"
    for table in ("garments", "photos", "wears", "looks", "look_items"):
        assert after[table] == before[table], table

    # The draft is still a draft, and the JSON columns read back.
    with db.connect() as c:
        p = db.row("profiles", c.execute("SELECT * FROM profiles WHERE id = 1").fetchone())
        assert p["settings"] == {} and p["measurements"] == {"chest": 98}
        assert c.execute("SELECT status FROM garments WHERE id = 4").fetchone()[0] == "draft"


def test_init_is_idempotent(data_dir):
    db.init()
    db.init()
    conn = sqlite3.connect(config.DB_PATH)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    finally:
        conn.close()


def test_daily_looks_unique_per_day_and_cascade(data_dir):
    db.init()
    with db.connect() as c:
        pid = db.insert(c, "profiles", {"name": "Sam"})
        db.insert(c, "daily_looks", {"profile_id": pid, "day": "2026-10-21", "options": [], "context": {}})
        try:
            db.insert(c, "daily_looks", {"profile_id": pid, "day": "2026-10-21"})
            raise AssertionError("second row for the same day should fail")
        except sqlite3.IntegrityError:
            pass
    with db.connect() as c:
        c.execute("DELETE FROM profiles WHERE id = ?", (pid,))
        assert c.execute("SELECT COUNT(*) FROM daily_looks").fetchone()[0] == 0
