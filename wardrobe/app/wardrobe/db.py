"""SQLite storage. One connection per call; WAL mode keeps the two of you from blocking each other."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime

from . import config

JSON_COLUMNS = {
    "garments": ["colors", "seasons", "occasions", "care", "measurements"],
    "profiles": ["measurements", "settings"],
    "fit_logs": ["areas"],
    "wishlist": ["colors"],
    "daily_looks": ["options", "context"],
}

MIGRATIONS = [
    # v1: initial schema
    """
    CREATE TABLE profiles (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        ha_user TEXT DEFAULT '',
        color TEXT DEFAULT '#2b3a67',
        measurements TEXT NOT NULL DEFAULT '{}',
        style_notes TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE garments (
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        subcategory TEXT DEFAULT '',
        brand TEXT DEFAULT '',
        size_label TEXT DEFAULT '',
        colors TEXT NOT NULL DEFAULT '[]',
        pattern TEXT DEFAULT 'solid',
        material TEXT DEFAULT '',
        formality INTEGER DEFAULT 3,
        warmth INTEGER DEFAULT 3,
        seasons TEXT NOT NULL DEFAULT '[]',
        occasions TEXT NOT NULL DEFAULT '[]',
        status TEXT DEFAULT 'active',
        care TEXT NOT NULL DEFAULT '{}',
        measurements TEXT NOT NULL DEFAULT '{}',
        fit_type TEXT DEFAULT 'regular',
        purchase_date TEXT,
        price REAL,
        favorite INTEGER DEFAULT 0,
        notes TEXT DEFAULT '',
        last_washed TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX idx_garments_profile ON garments(profile_id, category);
    CREATE TABLE photos (
        id INTEGER PRIMARY KEY,
        garment_id INTEGER NOT NULL REFERENCES garments(id) ON DELETE CASCADE,
        filename TEXT NOT NULL,
        kind TEXT DEFAULT 'item',
        is_primary INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX idx_photos_garment ON photos(garment_id);
    CREATE TABLE looks (
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        name TEXT DEFAULT '',
        occasion TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        rating INTEGER,
        source TEXT DEFAULT 'manual',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE look_items (
        look_id INTEGER NOT NULL REFERENCES looks(id) ON DELETE CASCADE,
        garment_id INTEGER NOT NULL REFERENCES garments(id) ON DELETE CASCADE,
        PRIMARY KEY (look_id, garment_id)
    );
    CREATE TABLE wears (
        id INTEGER PRIMARY KEY,
        garment_id INTEGER NOT NULL REFERENCES garments(id) ON DELETE CASCADE,
        look_id INTEGER REFERENCES looks(id) ON DELETE SET NULL,
        worn_on TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX idx_wears_garment ON wears(garment_id, worn_on);
    CREATE TABLE fit_logs (
        id INTEGER PRIMARY KEY,
        garment_id INTEGER NOT NULL REFERENCES garments(id) ON DELETE CASCADE,
        logged_on TEXT NOT NULL,
        overall TEXT DEFAULT 'right',
        areas TEXT NOT NULL DEFAULT '{}',
        notes TEXT DEFAULT '',
        photo_id INTEGER REFERENCES photos(id) ON DELETE SET NULL,
        ai_critique TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE wishlist (
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        category TEXT DEFAULT '',
        colors TEXT NOT NULL DEFAULT '[]',
        reason TEXT DEFAULT '',
        priority INTEGER DEFAULT 2,
        status TEXT DEFAULT 'open',
        url TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
    # v2 (0.4.0): profiles bound to a Home Assistant user ID, per-person settings, today's look
    """
    ALTER TABLE profiles ADD COLUMN ha_user_id TEXT DEFAULT '';
    ALTER TABLE profiles ADD COLUMN settings TEXT NOT NULL DEFAULT '{}';
    CREATE TABLE daily_looks (
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        day TEXT NOT NULL,
        options TEXT NOT NULL DEFAULT '[]',
        pick INTEGER NOT NULL DEFAULT 0,
        context TEXT NOT NULL DEFAULT '{}',
        worn INTEGER NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (profile_id, day)
    );
    """,
]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connect():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init() -> None:
    config.ensure_dirs()
    conn = _connect()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for idx, sql in enumerate(MIGRATIONS[version:], start=version + 1):
            # One transaction per migration, version included: a failed upgrade leaves the old schema.
            try:
                conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {idx};\nCOMMIT;")
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise
        conn.commit()
    finally:
        conn.close()


def row(table: str, r) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for col in JSON_COLUMNS.get(table, []):
        if col in d and isinstance(d[col], str):
            try:
                d[col] = json.loads(d[col])
            except ValueError:
                d[col] = [] if col in ("colors", "seasons", "occasions") else {}
    return d


def rows(table: str, rs) -> list[dict]:
    return [row(table, r) for r in rs]


def dump(table: str, values: dict) -> dict:
    out = dict(values)
    for col in JSON_COLUMNS.get(table, []):
        if col in out and not isinstance(out[col], str):
            out[col] = json.dumps(out[col])
    return out


def insert(conn, table: str, values: dict) -> int:
    values = dump(table, values)
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(values.values()))
    return cur.lastrowid


def update(conn, table: str, row_id: int, values: dict) -> None:
    if not values:
        return
    values = dump(table, values)
    sets = ", ".join(f"{k} = ?" for k in values)
    conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*values.values(), row_id])


def today() -> str:
    return date.today().isoformat()


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")
