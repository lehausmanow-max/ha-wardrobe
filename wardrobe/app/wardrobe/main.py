"""Wardrobe add-on: HTTP API and static UI, served through Home Assistant Ingress."""

import json
import logging
import re
from datetime import date
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import ai, care, colors, config, db, fit, ha, images, intake, matching, shopping, taxonomy

log = logging.getLogger("wardrobe")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
MEDIA_NAME = re.compile(r"^[0-9a-f]{32}\.jpg$")


# ------------------------------------------------------------------ helpers

def ok(data, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status)


def fail(status: int, message: str):
    raise HTTPException(status, message)


async def body(request: Request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        fail(400, "Request body must be JSON")
    if not isinstance(data, dict):
        fail(400, "Request body must be a JSON object")
    return data


def int_param(request: Request, name: str, required: bool = False) -> int | None:
    raw = request.query_params.get(name)
    if raw in (None, ""):
        if required:
            fail(400, f"Missing {name}")
        return None
    try:
        return int(raw)
    except ValueError:
        fail(400, f"{name} must be a number")


def _clamp_int(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _float_or_none(v):
    if v in (None, ""):
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def clean_garment(data: dict, partial: bool) -> dict:
    out = {}
    text = {"name": 80, "subcategory": 40, "brand": 60, "size_label": 20, "material": 120, "notes": 1000}
    for k, n in text.items():
        if k in data:
            out[k] = str(data[k] or "").strip()[:n]
    if "category" in data:
        if data["category"] not in taxonomy.CATEGORIES:
            fail(400, f"Unknown category {data['category']!r}")
        out["category"] = data["category"]
    if "colors" in data:
        out["colors"] = [h for h in (colors.normalize_hex(c) for c in data["colors"] or []) if h][:4]
    if "pattern" in data:
        out["pattern"] = data["pattern"] if data["pattern"] in taxonomy.PATTERNS else "solid"
    for k in ("formality", "warmth"):
        if k in data:
            out[k] = _clamp_int(data[k], 1, 5, 3)
    if "seasons" in data:
        out["seasons"] = [s for s in data["seasons"] or [] if s in taxonomy.SEASONS]
    if "occasions" in data:
        out["occasions"] = [s for s in data["occasions"] or [] if s in taxonomy.OCCASIONS]
    if "status" in data:
        if data["status"] not in taxonomy.STATUSES:
            fail(400, "Unknown status")
        out["status"] = data["status"]
    if "fit_type" in data:
        out["fit_type"] = data["fit_type"] if data["fit_type"] in taxonomy.FIT_TYPES else "regular"
    if "care" in data and isinstance(data["care"], dict):
        out["care"] = clean_care(data["care"])
    if "measurements" in data and isinstance(data["measurements"], dict):
        out["measurements"] = {k: f for k, v in data["measurements"].items()
                               if (f := _float_or_none(v)) is not None and f > 0}
    if "purchase_date" in data:
        pd = str(data["purchase_date"] or "")[:10]
        out["purchase_date"] = pd if re.match(r"^\d{4}-\d{2}-\d{2}$", pd) else None
    if "price" in data:
        out["price"] = _float_or_none(data["price"])
    if "favorite" in data:
        out["favorite"] = 1 if data["favorite"] else 0
    if not partial:
        if not out.get("name"):
            fail(400, "Give the garment a name")
        if "category" not in out:
            fail(400, "Choose a category")
    return out


def clean_care(raw: dict) -> dict:
    c = {}
    for k, allowed in taxonomy.CARE_FIELDS.items():
        v = raw.get(k)
        if k == "temp":
            v = _clamp_int(v, 0, 95, None) if v not in (None, "") else None
        elif v not in allowed:
            v = None
        if v is not None:
            c[k] = v
    c["notes"] = str(raw.get("notes") or "")[:300]
    c["wash_after"] = _clamp_int(raw.get("wash_after"), 0, 50, 0)
    return c


def finish_care(raw: dict, from_label: bool, stored: dict) -> dict:
    """Clean care for storing. Bleach is kept only when it was read from a care label: from this
    read (from_label), or from an earlier one already in the stored care."""
    c = clean_care(raw)
    if not from_label:
        return care.label_bleach(c, stored)
    if c.get("bleach"):
        c["bleach_from_label"] = True
    else:
        c.pop("bleach", None)
    return c


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


def get_garment(conn, gid: int) -> dict:
    g = db.row("garments", conn.execute("SELECT * FROM garments WHERE id = ?", (gid,)).fetchone())
    if not g:
        fail(404, "Garment not found")
    return enrich(conn, [g])[0]


def get_profile(conn, pid: int) -> dict:
    p = db.row("profiles", conn.execute("SELECT * FROM profiles WHERE id = ?", (pid,)).fetchone())
    if not p:
        fail(404, "Profile not found")
    return p


def list_garments(conn, profile_id: int, statuses=None) -> list[dict]:
    """A profile's garments, drafts left out."""
    q = "SELECT * FROM garments WHERE profile_id = ? AND status != ?"
    args: list = [profile_id, taxonomy.DRAFT]
    if statuses:
        q += f" AND status IN ({','.join('?' * len(statuses))})"
        args += list(statuses)
    return enrich(conn, db.rows("garments", conn.execute(q + " ORDER BY category, name", args)))


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


def provider(kind: str):
    return ai.build(kind, config.OPTIONS)


async def read_upload(request: Request, field: str = "file"):
    form = await request.form(max_part_size=images.MAX_UPLOAD_BYTES)
    upload = form.get(field)
    data = await upload.read() if upload is not None and hasattr(upload, "read") else None
    return form, data


def fix_primary(conn, garment_id: int) -> None:
    """Exactly one garment photo is the main photo, as long as the garment has one."""
    rows = conn.execute("SELECT id, kind, is_primary FROM photos WHERE garment_id = ? ORDER BY id",
                        (garment_id,)).fetchall()
    items = [r for r in rows if r["kind"] == "item"]
    main = next((r["id"] for r in items if r["is_primary"]), items[0]["id"] if items else None)
    conn.execute("UPDATE photos SET is_primary = CASE WHEN id = ? THEN 1 ELSE 0 END WHERE garment_id = ?",
                 (main, garment_id))


def purge_drafts(conn) -> None:
    """Drafts are kept for a day, so an interrupted intake can be continued; then they go."""
    old = [r[0] for r in conn.execute(
        "SELECT id FROM garments WHERE status = ? AND created_at < datetime('now', '-1 day')", (taxonomy.DRAFT,))]
    for gid in old:
        for (fn,) in conn.execute("SELECT filename FROM photos WHERE garment_id = ?", (gid,)).fetchall():
            images.delete_files(fn)
        conn.execute("DELETE FROM garments WHERE id = ?", (gid,))


async def store_photo(conn, garment_id: int, data: bytes, kind: str = "item") -> tuple[dict, object]:
    try:
        filename, img = await run_in_threadpool(images.save_upload, data)
    except images.ImageError as exc:
        fail(400, str(exc))
    has_primary = conn.execute("SELECT 1 FROM photos WHERE garment_id = ? AND kind = 'item' AND is_primary = 1",
                               (garment_id,)).fetchone()
    pid = db.insert(conn, "photos", {"garment_id": garment_id, "filename": filename, "kind": kind,
                                     "is_primary": 1 if kind == "item" and not has_primary else 0})
    return dict(conn.execute("SELECT * FROM photos WHERE id = ?", (pid,)).fetchone()), img


# ------------------------------------------------------------------ pages and media

async def index(request: Request):
    html = (STATIC_DIR / "index.html").read_text().replace("{{v}}", config.VERSION)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


async def media(request: Request):
    name = request.path_params["name"]
    folder = config.THUMB_DIR if request.url.path.startswith("/thumbs") else config.MEDIA_DIR
    path = folder / name
    if not MEDIA_NAME.match(name) or not path.exists():
        fail(404, "Photo not found")
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


# ------------------------------------------------------------------ meta and profiles

async def api_meta(request: Request):
    user = ha.ingress_user(request.headers)
    with db.connect() as conn:
        profiles = db.rows("profiles", conn.execute("SELECT * FROM profiles ORDER BY id"))
    matched = None
    names = {x.lower() for x in (user["name"], user["display_name"]) if x}
    for p in profiles:
        if (p.get("ha_user") or "").lower() in names or p["name"].lower() in names:
            matched = p["id"]
            break
    return ok({"version": config.VERSION, "taxonomy": taxonomy.meta(), "ai": ai.describe(config.OPTIONS),
               "ha_user": user, "matched_profile": matched, "profiles": profiles,
               "weather_configured": bool(config.OPTIONS.get("weather_entity")),
               "running_in_ha": bool(config.SUPERVISOR_TOKEN)})


async def api_profiles(request: Request):
    with db.connect() as conn:
        if request.method == "POST":
            data = await body(request)
            name = str(data.get("name") or "").strip()[:40]
            if not name:
                fail(400, "Give the profile a name")
            pid = db.insert(conn, "profiles", {"name": name, "ha_user": str(data.get("ha_user") or "")[:60],
                                               "color": colors.normalize_hex(data.get("color") or "") or "#2b3a67"})
            return ok(get_profile(conn, pid), 201)
        return ok(db.rows("profiles", conn.execute("SELECT * FROM profiles ORDER BY id")))


async def api_profile(request: Request):
    pid = request.path_params["id"]
    with db.connect() as conn:
        get_profile(conn, pid)
        if request.method == "DELETE":
            for (fn,) in conn.execute("SELECT p.filename FROM photos p JOIN garments g ON g.id = p.garment_id "
                                      "WHERE g.profile_id = ?", (pid,)).fetchall():
                images.delete_files(fn)
            conn.execute("DELETE FROM profiles WHERE id = ?", (pid,))
            return ok({"deleted": pid})
        data = await body(request)
        vals = {}
        if "name" in data:
            vals["name"] = str(data["name"] or "").strip()[:40] or None
        if "ha_user" in data:
            vals["ha_user"] = str(data["ha_user"] or "")[:60]
        if "color" in data:
            vals["color"] = colors.normalize_hex(data["color"] or "") or "#2b3a67"
        if "style_notes" in data:
            vals["style_notes"] = str(data["style_notes"] or "")[:1000]
        if "measurements" in data and isinstance(data["measurements"], dict):
            vals["measurements"] = {k: f for k, v in data["measurements"].items()
                                    if k in taxonomy.BODY_KEYS and (f := _float_or_none(v)) is not None and f > 0}
        db.update(conn, "profiles", pid, {k: v for k, v in vals.items() if v is not None})
        return ok(get_profile(conn, pid))


# ------------------------------------------------------------------ garments

async def api_garments(request: Request):
    with db.connect() as conn:
        if request.method == "POST":
            data = await body(request)
            vals = clean_garment(data, partial=False)
            pid = int(data.get("profile_id") or 0)
            get_profile(conn, pid)
            vals["profile_id"] = pid
            if not vals.get("care") or not vals["care"].get("wash"):
                vals["care"] = care.defaults_for(vals.get("material", ""), vals["category"])
            vals["care"] = care.label_bleach(vals["care"], {})
            gid = db.insert(conn, "garments", vals)
            return ok(get_garment(conn, gid), 201)

        profile_id = int_param(request, "profile_id", required=True)
        q = "SELECT * FROM garments WHERE profile_id = ?"
        args: list = [profile_id]
        cat = request.query_params.get("category")
        if cat:
            q += " AND category = ?"
            args.append(cat)
        status = request.query_params.get("status")
        if status == taxonomy.DRAFT:
            # Drafts to continue: only the last day's, older ones are deleted at the next intake.
            q += " AND status = ? AND created_at >= datetime('now', '-1 day')"
            args.append(taxonomy.DRAFT)
        elif status == "current":
            q += " AND status NOT IN ('archived', 'stored', ?)"
            args.append(taxonomy.DRAFT)
        elif status:
            q += " AND status = ?"
            args.append(status)
        else:
            q += " AND status != ?"
            args.append(taxonomy.DRAFT)
        search = (request.query_params.get("q") or "").strip()
        if search:
            q += " AND (name LIKE ? OR brand LIKE ? OR material LIKE ? OR subcategory LIKE ? OR notes LIKE ?)"
            args += [f"%{search}%"] * 5
        garments = enrich(conn, db.rows("garments", conn.execute(q + " ORDER BY updated_at DESC", args)))
        return ok(garments)


async def api_garment(request: Request):
    gid = request.path_params["id"]
    with db.connect() as conn:
        g = get_garment(conn, gid)
        if request.method == "DELETE":
            for p in g["photos"]:
                images.delete_files(p["filename"])
            conn.execute("DELETE FROM garments WHERE id = ?", (gid,))
            return ok({"deleted": gid})
        if request.method == "PUT":
            vals = clean_garment(await body(request), partial=True)
            if "care" in vals:
                vals["care"] = care.label_bleach(vals["care"], g.get("care") or {})
            vals["updated_at"] = db.now()
            db.update(conn, "garments", gid, vals)
            return ok(get_garment(conn, gid))

        profile = get_profile(conn, g["profile_id"])
        verdicts = fit.assess(g, profile.get("measurements") or {})
        logs = db.rows("fit_logs", conn.execute(
            "SELECT * FROM fit_logs WHERE garment_id = ? ORDER BY logged_on DESC, id DESC", (gid,)))
        for lg in logs:
            ph = conn.execute("SELECT filename FROM photos WHERE id = ?", (lg["photo_id"],)).fetchone() \
                if lg["photo_id"] else None
            lg["photo"] = ph[0] if ph else None
        wears = [r[0] for r in conn.execute(
            "SELECT worn_on FROM wears WHERE garment_id = ? ORDER BY worn_on DESC LIMIT 20", (gid,))]
        looks = [dict(r) for r in conn.execute(
            "SELECT l.id, l.name, l.occasion FROM looks l JOIN look_items li ON li.look_id = l.id "
            "WHERE li.garment_id = ? ORDER BY l.id DESC", (gid,))]
        g.update(fit_verdicts=verdicts, fit_summary=fit.summary(verdicts), fit_logs=logs,
                 wears=wears, looks=looks,
                 suggested_care=care.defaults_for(g.get("material", ""), g["category"]),
                 cost_per_wear=round(g["price"] / max(1, g["wear_count"]), 2) if g.get("price") else None)
        return ok(g)


async def api_garment_photo(request: Request):
    gid = request.path_params["id"]
    form, data = await read_upload(request)
    if not data:
        fail(400, "Attach a photo")
    kind = form.get("kind") if form.get("kind") in taxonomy.PHOTO_KINDS else "item"
    with db.connect() as conn:
        g = get_garment(conn, gid)
        _, img = await store_photo(conn, gid, data, kind)
        if kind == "item" and not g.get("colors"):
            db.update(conn, "garments", gid, {"colors": images.dominant_colors(img)})
        return ok(get_garment(conn, gid), 201)


async def api_photo(request: Request):
    pid = request.path_params["id"]
    with db.connect() as conn:
        p = conn.execute("SELECT * FROM photos WHERE id = ?", (pid,)).fetchone()
        if not p:
            fail(404, "Photo not found")
        if request.method == "DELETE":
            images.delete_files(p["filename"])
            conn.execute("DELETE FROM photos WHERE id = ?", (pid,))
        elif request.method == "PATCH":  # change what the photo shows
            kind = (await body(request)).get("kind")
            if kind not in taxonomy.PHOTO_KINDS:
                fail(400, "Unknown photo kind")
            conn.execute("UPDATE photos SET kind = ? WHERE id = ?", (kind, pid))
        else:  # POST = make it the main photo, which is always a photo of the garment itself
            conn.execute("UPDATE photos SET is_primary = 0 WHERE garment_id = ?", (p["garment_id"],))
            conn.execute("UPDATE photos SET is_primary = 1, kind = 'item' WHERE id = ?", (pid,))
        fix_primary(conn, p["garment_id"])
        return ok(get_garment(conn, p["garment_id"]))


async def api_intake(request: Request):
    """Start a draft garment from its first photo. Nothing is read yet: that waits until all photos are in."""
    form, data = await read_upload(request)
    if not data:
        fail(400, "Attach a photo")
    try:
        profile_id = int(form.get("profile_id") or 0)
    except ValueError:
        fail(400, "profile_id must be a number")
    kind = form.get("kind") if form.get("kind") in intake.READ_KINDS else "item"
    with db.connect() as conn:
        get_profile(conn, profile_id)
        purge_drafts(conn)
        gid = db.insert(conn, "garments", {"profile_id": profile_id, "name": "New garment", "category": "top",
                                           "status": taxonomy.DRAFT, "care": care.defaults_for("", "top")})
        _, img = await store_photo(conn, gid, data, kind)
        if kind == "item":
            db.update(conn, "garments", gid, {"colors": images.dominant_colors(img)})
        return ok(get_garment(conn, gid), 201)


async def api_read(request: Request):
    """Read all photos of a garment in one go. A draft is filled in; a saved garment gets proposals."""
    gid = request.path_params["id"]
    data = await body(request) if await request.body() else {}
    keep = set()
    for i in data.get("keep") or []:
        try:
            keep.add(int(i))
        except (TypeError, ValueError):
            pass
    vision = provider("vision")
    if not vision:
        fail(400, "Turn on an AI vision provider in the app's configuration to read photos")
    with db.connect() as conn:
        g = get_garment(conn, gid)
    if not intake.pick_photos(g["photos"]):
        fail(400, "Add a photo of the garment or its label first")
    try:
        result = await run_in_threadpool(intake.read, vision, g["photos"], keep)
    except ai.AIError as exc:
        fail(502, f"Couldn't read the photos: {exc}")

    with db.connect() as conn:
        g = get_garment(conn, gid)
        fresh = g["status"] == taxonomy.DRAFT
        kinds = intake.kinds_after(g["photos"], result["roles"], keep)
        for p in g["photos"]:
            if kinds[p["id"]] != p["kind"]:
                conn.execute("UPDATE photos SET kind = ? WHERE id = ?", (kinds[p["id"]], p["id"]))
        if fresh and not any(p["is_primary"] and p["id"] in keep for p in g["photos"]):
            front = next((pid for pid, role in result["roles"].items()
                          if role == "front" and kinds.get(pid) == "item"), None)
            if front:
                conn.execute("UPDATE photos SET is_primary = CASE WHEN id = ? THEN 1 ELSE 0 END "
                             "WHERE garment_id = ?", (front, gid))
        fix_primary(conn, gid)
        g = get_garment(conn, gid)

        local = None
        if fresh and not result["garment"].get("colors") and g["photo"]:
            local = await run_in_threadpool(images.colors_of, g["photo"])
        merged = intake.merge(g, result, fresh, {p["kind"] for p in g["photos"]}, local)
        info = {"provider": vision.name, "confidence": result["confidence"],
                "sources": {k: src for k, (_, src) in merged.items()}}
        if not fresh:
            return ok({"garment": g, "read": info, "proposals": intake.proposals(g, merged)})
        vals = clean_garment({k: v for k, (v, _) in merged.items() if k != "care"}, partial=True)
        if "care" in merged:
            new_care, src = merged["care"]
            vals["care"] = finish_care(new_care, src == "label", g.get("care") or {})
        vals["updated_at"] = db.now()
        db.update(conn, "garments", gid, vals)
        return ok({"garment": get_garment(conn, gid), "read": info})


async def api_read_apply(request: Request):
    """Apply the proposals the owner ticked after a re-read."""
    gid = request.path_params["id"]
    data = await body(request)
    values = data.get("values")
    values = {k: v for k, v in values.items() if k in intake.FIELD_ORDER} if isinstance(values, dict) else {}
    if not values:
        fail(400, "Nothing selected")
    with db.connect() as conn:
        g = get_garment(conn, gid)
        vals = clean_garment({k: v for k, v in values.items() if k != "care"}, partial=True)
        if isinstance(values.get("care"), dict):
            vals["care"] = finish_care(values["care"], bool(data.get("care_from_label")), g.get("care") or {})
        vals["updated_at"] = db.now()
        db.update(conn, "garments", gid, vals)
        return ok(get_garment(conn, gid))


async def api_wear(request: Request):
    gid = request.path_params["id"]
    data = await body(request) if await request.body() else {}
    worn_on = str(data.get("date") or db.today())[:10]
    with db.connect() as conn:
        get_garment(conn, gid)
        db.insert(conn, "wears", {"garment_id": gid, "worn_on": worn_on})
        return ok(get_garment(conn, gid))


# ------------------------------------------------------------------ care and laundry

async def api_care_defaults(request: Request):
    return ok(care.defaults_for(request.query_params.get("material", ""),
                                request.query_params.get("category", "")))


async def api_laundry(request: Request):
    profile_id = int_param(request, "profile_id")
    with db.connect() as conn:
        pids = [profile_id] if profile_id else [r[0] for r in conn.execute("SELECT id FROM profiles")]
        basket, due = [], []
        for pid in pids:
            for g in list_garments(conn, pid, ("laundry", "active")):
                if g["status"] == "laundry":
                    basket.append(g)
                elif g["wash_due"]:
                    due.append(g)
        return ok({"loads": care.sort_laundry(basket), "due": due, "count": len(basket)})


async def api_laundry_done(request: Request):
    data = await body(request)
    ids = [int(i) for i in data.get("ids") or []]
    if not ids:
        fail(400, "Nothing selected")
    with db.connect() as conn:
        marks = ",".join("?" * len(ids))
        conn.execute(f"UPDATE garments SET status = 'active', last_washed = datetime('now'), "
                     f"updated_at = datetime('now') WHERE id IN ({marks})", ids)
    return ok({"washed": ids})


# ------------------------------------------------------------------ looks

async def api_weather(request: Request):
    return ok(await run_in_threadpool(ha.weather))


def _ctx(conn, profile_id: int, data: dict) -> matching.Context:
    temp = data.get("temp")
    try:
        temp = float(temp) if temp not in (None, "") else None
    except (TypeError, ValueError):
        temp = None
    return matching.Context(occasion=data.get("occasion") or None, temp=temp,
                            last_worn=last_worn_map(conn, profile_id),
                            look_ratings=look_ratings(conn, profile_id))


async def api_suggest(request: Request):
    data = await body(request)
    profile_id = int(data.get("profile_id") or 0)
    with db.connect() as conn:
        profile = get_profile(conn, profile_id)
        if data.get("temp") in (None, "") and data.get("use_weather", True):
            w = await run_in_threadpool(ha.weather)
            if w and w.get("temperature") is not None:
                data["temp"] = w["temperature"]
        ctx = _ctx(conn, profile_id, data)
        garments = list_garments(conn, profile_id, ("active",))
    anchor = int(data["anchor_id"]) if data.get("anchor_id") else None
    looks = await run_in_threadpool(matching.suggest, garments, ctx, anchor, int(data.get("count") or 6))
    result = {"context": ctx.public(), "looks": looks, "ai": None}
    text = provider("text")
    if data.get("ai") and text and looks:
        context = ctx.public() | {"style_notes": profile.get("style_notes") or ""}
        try:
            picks = await run_in_threadpool(ai.tasks.style_looks, text, looks, context)
            for p in picks:
                looks[p["index"]]["ai"] = {"why": p["why"], "tip": p["tip"]}
            order = [p["index"] for p in picks]
            result["looks"] = [looks[i] for i in order] + [lk for i, lk in enumerate(looks) if i not in order]
            result["ai"] = {"provider": text.name}
        except ai.AIError as exc:
            result["ai"] = {"error": str(exc)}
    return ok(result)


async def api_evaluate(request: Request):
    data = await body(request)
    ids = [int(i) for i in data.get("garment_ids") or []]
    with db.connect() as conn:
        if not ids:
            return ok({"score": 0, "reasons": [], "warnings": ["Pick at least two pieces"]})
        marks = ",".join("?" * len(ids))
        garments = enrich(conn, db.rows("garments", conn.execute(
            f"SELECT * FROM garments WHERE id IN ({marks})", ids)))
        ctx = _ctx(conn, garments[0]["profile_id"], data) if garments else matching.Context()
    return ok(matching.score(garments, ctx, with_weather=ctx.temp is not None))


def _look_out(conn, look) -> dict:
    d = dict(look)
    ids = [r[0] for r in conn.execute("SELECT garment_id FROM look_items WHERE look_id = ?", (d["id"],))]
    items = enrich(conn, db.rows("garments", conn.execute(
        f"SELECT * FROM garments WHERE id IN ({','.join('?' * len(ids))})", ids))) if ids else []
    d["items"] = matching._order(items)
    d["score"] = matching.score(items, matching.Context(), with_weather=False) if items else None
    return d


async def api_looks(request: Request):
    with db.connect() as conn:
        if request.method == "POST":
            data = await body(request)
            pid = int(data.get("profile_id") or 0)
            get_profile(conn, pid)
            ids = [int(i) for i in data.get("garment_ids") or []]
            if len(ids) < 2:
                fail(400, "A look needs at least two pieces")
            lid = db.insert(conn, "looks", {
                "profile_id": pid, "name": str(data.get("name") or "")[:60],
                "occasion": data.get("occasion") if data.get("occasion") in taxonomy.OCCASIONS else "",
                "notes": str(data.get("notes") or "")[:500],
                "rating": _clamp_int(data.get("rating"), 1, 5, None) if data.get("rating") else None,
                "source": "suggested" if data.get("source") == "suggested" else "manual"})
            for gid in ids:
                conn.execute("INSERT OR IGNORE INTO look_items (look_id, garment_id) VALUES (?, ?)", (lid, gid))
            return ok(_look_out(conn, conn.execute("SELECT * FROM looks WHERE id = ?", (lid,)).fetchone()), 201)
        pid = int_param(request, "profile_id", required=True)
        looks = conn.execute("SELECT * FROM looks WHERE profile_id = ? ORDER BY id DESC", (pid,)).fetchall()
        return ok([_look_out(conn, lk) for lk in looks])


async def api_look(request: Request):
    lid = request.path_params["id"]
    with db.connect() as conn:
        look = conn.execute("SELECT * FROM looks WHERE id = ?", (lid,)).fetchone()
        if not look:
            fail(404, "Look not found")
        if request.method == "DELETE":
            conn.execute("DELETE FROM looks WHERE id = ?", (lid,))
            return ok({"deleted": lid})
        data = await body(request)
        vals = {}
        if "name" in data:
            vals["name"] = str(data["name"] or "")[:60]
        if "notes" in data:
            vals["notes"] = str(data["notes"] or "")[:500]
        if "rating" in data:
            vals["rating"] = _clamp_int(data["rating"], 1, 5, None) if data["rating"] else None
        if "occasion" in data:
            vals["occasion"] = data["occasion"] if data["occasion"] in taxonomy.OCCASIONS else ""
        if vals:
            sets = ", ".join(f"{k} = ?" for k in vals)
            conn.execute(f"UPDATE looks SET {sets} WHERE id = ?", [*vals.values(), lid])
        if "garment_ids" in data:
            conn.execute("DELETE FROM look_items WHERE look_id = ?", (lid,))
            for gid in data["garment_ids"]:
                conn.execute("INSERT OR IGNORE INTO look_items (look_id, garment_id) VALUES (?, ?)", (lid, int(gid)))
        return ok(_look_out(conn, conn.execute("SELECT * FROM looks WHERE id = ?", (lid,)).fetchone()))


async def api_look_wear(request: Request):
    lid = request.path_params["id"]
    data = await body(request) if await request.body() else {}
    worn_on = str(data.get("date") or db.today())[:10]
    with db.connect() as conn:
        ids = [r[0] for r in conn.execute("SELECT garment_id FROM look_items WHERE look_id = ?", (lid,))]
        if not ids:
            fail(404, "Look not found")
        for gid in ids:
            db.insert(conn, "wears", {"garment_id": gid, "look_id": lid, "worn_on": worn_on})
    return ok({"logged": len(ids), "date": worn_on})


async def api_wear_items(request: Request):
    """Log a wear for an unsaved suggestion: a list of garment ids."""
    data = await body(request)
    ids = [int(i) for i in data.get("garment_ids") or []]
    worn_on = str(data.get("date") or db.today())[:10]
    with db.connect() as conn:
        for gid in ids:
            db.insert(conn, "wears", {"garment_id": gid, "worn_on": worn_on})
    return ok({"logged": len(ids), "date": worn_on})


# ------------------------------------------------------------------ fit

async def api_fit_log(request: Request):
    gid = request.path_params["id"]
    form, data = await read_upload(request)
    overall = form.get("overall") if form.get("overall") in taxonomy.FIT_OVERALL else "right"
    try:
        areas = json.loads(form.get("areas") or "{}")
    except ValueError:
        areas = {}
    areas = {k: _clamp_int(v, -2, 2, 0) for k, v in areas.items() if k in taxonomy.FIT_AREAS and v not in (0, "0")}
    notes = str(form.get("notes") or "")[:500]
    with db.connect() as conn:
        g = get_garment(conn, gid)
        photo_id, critique, ai_error = None, "", None
        if data:
            photo, _ = await store_photo(conn, gid, data, "worn")
            photo_id = photo["id"]
            vision = provider("vision")
            if vision:
                profile = get_profile(conn, g["profile_id"])
                verdicts = fit.assess(g, profile.get("measurements") or {})
                try:
                    critique = await run_in_threadpool(
                        ai.tasks.critique_fit, vision, images.for_ai(photo["filename"]), g, verdicts,
                        {"overall": overall, "areas": areas, "notes": notes})
                except ai.AIError as exc:
                    ai_error = str(exc)
        lid = db.insert(conn, "fit_logs", {"garment_id": gid, "logged_on": db.today(), "overall": overall,
                                           "areas": areas, "notes": notes, "photo_id": photo_id,
                                           "ai_critique": critique})
        out = db.row("fit_logs", conn.execute("SELECT * FROM fit_logs WHERE id = ?", (lid,)).fetchone())
        out["ai_error"] = ai_error
        return ok(out, 201)


async def api_fit_log_delete(request: Request):
    with db.connect() as conn:
        conn.execute("DELETE FROM fit_logs WHERE id = ?", (request.path_params["id"],))
    return ok({"deleted": request.path_params["id"]})


async def api_fit_overview(request: Request):
    pid = int_param(request, "profile_id", required=True)
    with db.connect() as conn:
        profile = get_profile(conn, pid)
        garments = list_garments(conn, pid)
        logs: dict[int, list] = {}
        for r in db.rows("fit_logs", conn.execute(
                "SELECT f.* FROM fit_logs f JOIN garments g ON g.id = f.garment_id WHERE g.profile_id = ? "
                "ORDER BY f.logged_on DESC, f.id DESC", (pid,))):
            logs.setdefault(r["garment_id"], []).append(r)
    body_m = profile.get("measurements") or {}
    flagged, measured = [], 0
    for g in garments:
        verdicts = fit.assess(g, body_m)
        if verdicts:
            measured += 1
        bad = [v for v in verdicts if v["band"] in ("tight", "loose")]
        recent = logs.get(g["id"], [])
        if bad or (recent and recent[0]["overall"] in ("too_small", "too_big")):
            flagged.append({"id": g["id"], "name": g["name"], "photo": g["photo"],
                            "summary": fit.summary(verdicts) or f"You logged it as {recent[0]['overall'].replace('_', ' ')}"})
    names = {g["id"]: g["name"] for g in garments}
    recent_logs = sorted((lg | {"garment": names.get(lg["garment_id"])} for v in logs.values() for lg in v),
                         key=lambda x: (x["logged_on"], x["id"]), reverse=True)[:15]
    return ok({"measurements": body_m, "brands": fit.brand_notes(garments, logs), "flagged": flagged,
               "measured_garments": measured, "recent_logs": recent_logs})


# ------------------------------------------------------------------ shopping

def _wear_dates(conn, pid) -> dict[int, list[date]]:
    out: dict[int, list[date]] = {}
    for r in conn.execute("SELECT w.garment_id, w.worn_on FROM wears w JOIN garments g ON g.id = w.garment_id "
                          "WHERE g.profile_id = ?", (pid,)):
        out.setdefault(r[0], []).append(date.fromisoformat(r[1]))
    return out


async def api_shopping(request: Request):
    pid = int_param(request, "profile_id", required=True)
    with db.connect() as conn:
        get_profile(conn, pid)
        garments = list_garments(conn, pid)
        wears = _wear_dates(conn, pid)
        wishlist = db.rows("wishlist", conn.execute(
            "SELECT * FROM wishlist WHERE profile_id = ? ORDER BY status = 'open' DESC, priority, id DESC", (pid,)))
    analysis = await run_in_threadpool(shopping.analyse, garments, wears)
    analysis["wishlist"] = wishlist
    return ok(analysis)


async def api_shopping_ai(request: Request):
    data = await body(request)
    pid = int(data.get("profile_id") or 0)
    text = provider("text")
    if not text:
        fail(400, "Turn on an AI text provider in the add-on settings to get written advice")
    with db.connect() as conn:
        profile = get_profile(conn, pid)
        garments = list_garments(conn, pid)
        wears = _wear_dates(conn, pid)
    analysis = await run_in_threadpool(shopping.analyse, garments, wears)
    summary = {
        "style_notes": profile.get("style_notes") or "",
        "wardrobe": [{"name": g["name"], "category": g["category"], "colour": (g["color_names"] or ["?"])[0],
                      "formality": g["formality"], "wears": g["wear_count"]} for g in garments[:80]],
        "best_next_buys_by_outfits_unlocked": analysis["buys"][:6],
        "gaps": analysis["gaps"], "hard_to_style": [h["name"] for h in analysis["hard_to_style"]],
        "saturated": analysis["saturated"],
    }
    try:
        advice = await run_in_threadpool(ai.tasks.shopping_advice, text, summary)
    except ai.AIError as exc:
        fail(502, str(exc))
    return ok({"advice": advice, "provider": text.name})


async def api_wishlist(request: Request):
    with db.connect() as conn:
        if request.method == "POST":
            data = await body(request)
            pid = int(data.get("profile_id") or 0)
            get_profile(conn, pid)
            title = str(data.get("title") or "").strip()[:80]
            if not title:
                fail(400, "Name the item")
            wid = db.insert(conn, "wishlist", {
                "profile_id": pid, "title": title,
                "category": data.get("category") if data.get("category") in taxonomy.CATEGORIES else "",
                "colors": [h for h in (colors.normalize_hex(c) for c in data.get("colors") or []) if h],
                "reason": str(data.get("reason") or "")[:300], "priority": _clamp_int(data.get("priority"), 1, 3, 2),
                "url": str(data.get("url") or "")[:500]})
            return ok(db.row("wishlist", conn.execute("SELECT * FROM wishlist WHERE id = ?", (wid,)).fetchone()), 201)
        pid = int_param(request, "profile_id", required=True)
        return ok(db.rows("wishlist", conn.execute("SELECT * FROM wishlist WHERE profile_id = ? ORDER BY id DESC",
                                                   (pid,))))


async def api_wishlist_item(request: Request):
    wid = request.path_params["id"]
    with db.connect() as conn:
        if request.method == "DELETE":
            conn.execute("DELETE FROM wishlist WHERE id = ?", (wid,))
            return ok({"deleted": wid})
        data = await body(request)
        vals = {}
        if data.get("status") in ("open", "bought", "dropped"):
            vals["status"] = data["status"]
        for k in ("title", "reason", "url"):
            if k in data:
                vals[k] = str(data[k] or "")[:500]
        if "priority" in data:
            vals["priority"] = _clamp_int(data["priority"], 1, 3, 2)
        db.update(conn, "wishlist", wid, vals)
        return ok(db.row("wishlist", conn.execute("SELECT * FROM wishlist WHERE id = ?", (wid,)).fetchone()))


async def api_export(request: Request):
    # Drafts are unfinished garments: left out, with their photos.
    queries = {t: f"SELECT * FROM {t}" for t in ("profiles", "looks", "look_items", "wears", "fit_logs", "wishlist")}
    queries["garments"] = "SELECT * FROM garments WHERE status != :draft"
    queries["photos"] = ("SELECT p.* FROM photos p JOIN garments g ON g.id = p.garment_id "
                         "WHERE g.status != :draft ORDER BY p.id")
    order = ("profiles", "garments", "photos", "looks", "look_items", "wears", "fit_logs", "wishlist")
    with db.connect() as conn:
        dump = {t: [dict(r) for r in conn.execute(queries[t], {"draft": taxonomy.DRAFT})] for t in order}
    dump["version"] = config.VERSION
    return Response(json.dumps(dump, indent=1), media_type="application/json",
                    headers={"Content-Disposition": f"attachment; filename=wardrobe-{db.today()}.json"})


# ------------------------------------------------------------------ app

async def http_error(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
    return Response(exc.detail, status_code=exc.status_code)


async def server_error(request: Request, exc: Exception):
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse({"error": "Something broke on the server. Check the add-on log."}, status_code=500)


class IngressOnly:
    """Under the Supervisor, accept requests only from the Ingress proxy."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and config.INGRESS_ONLY:
            client = (scope.get("client") or ("", 0))[0]
            if client != config.INGRESS_PROXY_IP:
                await Response("Open this app from the Home Assistant sidebar.", 403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


routes = [
    Route("/", index),
    Route("/media/{name}", media),
    Route("/thumbs/{name}", media),
    Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
    Route("/api/meta", api_meta),
    Route("/api/profiles", api_profiles, methods=["GET", "POST"]),
    Route("/api/profiles/{id:int}", api_profile, methods=["PUT", "DELETE"]),
    Route("/api/garments", api_garments, methods=["GET", "POST"]),
    Route("/api/garments/{id:int}", api_garment, methods=["GET", "PUT", "DELETE"]),
    Route("/api/garments/{id:int}/photos", api_garment_photo, methods=["POST"]),
    Route("/api/garments/{id:int}/read", api_read, methods=["POST"]),
    Route("/api/garments/{id:int}/read/apply", api_read_apply, methods=["POST"]),
    Route("/api/garments/{id:int}/wear", api_wear, methods=["POST"]),
    Route("/api/garments/{id:int}/fit-log", api_fit_log, methods=["POST"]),
    Route("/api/photos/{id:int}", api_photo, methods=["POST", "PATCH", "DELETE"]),
    Route("/api/intake", api_intake, methods=["POST"]),
    Route("/api/care/defaults", api_care_defaults),
    Route("/api/laundry", api_laundry),
    Route("/api/laundry/done", api_laundry_done, methods=["POST"]),
    Route("/api/weather", api_weather),
    Route("/api/suggest", api_suggest, methods=["POST"]),
    Route("/api/evaluate", api_evaluate, methods=["POST"]),
    Route("/api/looks", api_looks, methods=["GET", "POST"]),
    Route("/api/looks/{id:int}", api_look, methods=["PUT", "DELETE"]),
    Route("/api/looks/{id:int}/wear", api_look_wear, methods=["POST"]),
    Route("/api/wear", api_wear_items, methods=["POST"]),
    Route("/api/fit-logs/{id:int}", api_fit_log_delete, methods=["DELETE"]),
    Route("/api/fit/overview", api_fit_overview),
    Route("/api/shopping", api_shopping),
    Route("/api/shopping/ai", api_shopping_ai, methods=["POST"]),
    Route("/api/wishlist", api_wishlist, methods=["GET", "POST"]),
    Route("/api/wishlist/{id:int}", api_wishlist_item, methods=["PUT", "DELETE"]),
    Route("/api/export", api_export),
]


def create_app() -> Starlette:
    logging.basicConfig(level=getattr(logging, str(config.OPTIONS.get("log_level", "info")).upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db.init()
    log.info("Wardrobe %s ready. AI: %s", config.VERSION, ai.describe(config.OPTIONS))
    application = Starlette(routes=routes, exception_handlers={HTTPException: http_error, Exception: server_error})
    application.add_middleware(IngressOnly)
    return application


app = create_app()
