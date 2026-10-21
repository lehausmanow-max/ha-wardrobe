"""Reading garments with their photos and wear history. Shared by the HTTP API and today's look."""

from datetime import date

from . import colors, db, taxonomy


def _wear_stats(conn, ids: list[int]) -> dict[int, dict]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    stats = {i: {"wear_count": 0, "last_worn": None, "wears_since_wash": 0} for i in ids}
    for r in conn.execute(f"SELECT garment_id, COUNT(*) n, MAX(worn_on) last FROM wears "
                          f"WHERE garment_id IN ({marks}) GROUP BY garment_id", ids):
        stats[r["garment_id"]].update(wear_count=r["n"], last_worn=r["last"])
    for r in conn.execute(
            f"SELECT w.garment_id, COUNT(*) n FROM wears w JOIN garments g ON g.id = w.garment_id "
            f"WHERE w.garment_id IN ({marks}) AND (g.last_washed IS NULL OR w.created_at > g.last_washed) "
            f"GROUP BY w.garment_id", ids):
        stats[r["garment_id"]]["wears_since_wash"] = r["n"]
    return stats


def _photos(conn, ids: list[int]) -> dict[int, list[dict]]:
    out = {i: [] for i in ids}
    if not ids:
        return out
    marks = ",".join("?" * len(ids))
    for r in conn.execute(f"SELECT * FROM photos WHERE garment_id IN ({marks}) "
                          f"ORDER BY is_primary DESC, id", ids):
        out[r["garment_id"]].append(dict(r))
    return out


def enrich(conn, garments: list[dict]) -> list[dict]:
    ids = [g["id"] for g in garments]
    photos = _photos(conn, ids)
    stats = _wear_stats(conn, ids)
    for g in garments:
        g["photos"] = photos.get(g["id"], [])
        item_photos = [p for p in g["photos"] if p["kind"] == "item"]
        g["photo"] = (next((p for p in item_photos if p["is_primary"]), None)
                      or (item_photos[0] if item_photos else None))
        g["photo"] = g["photo"]["filename"] if g["photo"] else None
        g.update(stats.get(g["id"], {}))
        wash_after = int((g.get("care") or {}).get("wash_after") or 0)
        g["wash_due"] = bool(wash_after and g["wears_since_wash"] >= wash_after and g["status"] == "active")
        g["color_names"] = [colors.name_of(c) for c in g.get("colors") or []]
        # Bleach shows only when it was read from a care label (see care.label_bleach). Garments
        # saved before 0.2.0 carry no marker; for those a care-label photo counts as one.
        c = g.get("care") or {}
        if "bleach_from_label" not in c and c.get("bleach"):
            c["bleach_from_label"] = any(p["kind"] == "label" for p in g["photos"])
        if not (c.get("bleach") and c.get("bleach_from_label")):
            c.pop("bleach", None)
            c.pop("bleach_from_label", None)
    return garments


def list_garments(conn, profile_id: int, statuses=None) -> list[dict]:
    """A profile's garments, drafts left out."""
    q = "SELECT * FROM garments WHERE profile_id = ? AND status != ?"
    args: list = [profile_id, taxonomy.DRAFT]
    if statuses:
        q += f" AND status IN ({','.join('?' * len(statuses))})"
        args += list(statuses)
    return enrich(conn, db.rows("garments", conn.execute(q + " ORDER BY category, name", args)))


def by_ids(conn, ids: list[int]) -> list[dict]:
    """Garments by id, in the order given; ids that no longer exist are skipped."""
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    found = {g["id"]: g for g in enrich(conn, db.rows("garments", conn.execute(
        f"SELECT * FROM garments WHERE id IN ({marks})", ids)))}
    return [found[i] for i in ids if i in found]


def last_worn_map(conn, profile_id: int) -> dict[int, date]:
    out = {}
    for r in conn.execute("SELECT w.garment_id, MAX(w.worn_on) d FROM wears w JOIN garments g "
                          "ON g.id = w.garment_id WHERE g.profile_id = ? GROUP BY w.garment_id",
                          (profile_id,)):
        out[r["garment_id"]] = date.fromisoformat(r["d"])
    return out


def look_ratings(conn, profile_id: int) -> dict:
    ratings: dict = {}
    looks = conn.execute("SELECT id, rating FROM looks WHERE profile_id = ?", (profile_id,)).fetchall()
    for look in looks:
        ids = frozenset(r[0] for r in conn.execute(
            "SELECT garment_id FROM look_items WHERE look_id = ?", (look["id"],)))
        ratings[ids] = look["rating"]
    return ratings
