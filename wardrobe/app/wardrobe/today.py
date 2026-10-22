"""Today's look: one ranked list of looks per person per day, picked for the forecast.

The same functions serve the app (Today card) and Home Assistant (wardrobe_command), so both
always show the same look. All of it is blocking database work: call it from a thread.
"""

import logging
import re
import unicodedata
from datetime import date

from . import agenda, config, db, garments, ha, matching

log = logging.getLogger("wardrobe.today")
COUNT = 8
MAX_STATE = 255
_weather_failing = False
_calendar_failing = False


# ------------------------------------------------------------------ names

def slug(name: str, profile_id: int | None = None) -> str:
    """ASCII lowercase, everything else turned into '_': 'Anna B.' -> 'anna_b'."""
    ascii_name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")
    return s or f"profile_{profile_id}"


def profile_slug(profile: dict) -> str:
    return slug(profile["name"], profile["id"])


def entity_id(profile: dict) -> str:
    return f"sensor.wardrobe_today_{profile_slug(profile)}"


# ------------------------------------------------------------------ building

def _why_none(clean: list[dict]) -> str:
    cats = {g["category"] for g in clean}
    has_upper = "top" in cats or any(g["category"] == "knitwear" and g.get("subcategory") not in matching.LAYER_ONLY
                                     for g in clean)
    if not clean:
        return "No clean clothes: add garments or empty the wash basket"
    if "dress" not in cats and not (has_upper and "bottom" in cats):
        need = [w for w, ok in (("top", has_upper), ("bottom", "bottom" in cats)) if not ok]
        return f"Needs a clean {' and a clean '.join(need)}, or a clean dress"
    return "Nothing scores well enough yet: add a few more clean pieces"


def get_row(conn, profile_id: int, day: str) -> dict | None:
    return db.row("daily_looks", conn.execute(
        "SELECT * FROM daily_looks WHERE profile_id = ? AND day = ?", (profile_id, day)).fetchone())


def build(conn, profile: dict, day: str | None = None, refresh: bool = False, weather=None,
          calendar=None) -> dict:
    """Rank today's looks and store them. An existing row is replaced on refresh, and when it
    has no look (so clothes added since count without a refresh).

    weather: a dict like ha.forecast() returns, or a callable taking the date and returning one
    (called only when building). None means no weather.
    calendar: a list of events like ha.calendar_events() returns, or a callable taking the profile
    and the date and returning one. None means no calendar: a casual day."""
    day = day or db.today()
    existing = get_row(conn, profile["id"], day)
    if existing and existing["options"] and not refresh:
        return existing
    replace = refresh or bool(existing)
    wx = _weather(weather, day)
    cal = agenda.match(_events(calendar, profile, day), agenda.words_for(profile.get("settings")))
    pid = profile["id"]
    clean = garments.list_garments(conn, pid, ("active",))
    looks, ctx = _rank(conn, pid, clean, cal["occasion"], wx, day)
    if not looks and cal["occasion"] != "casual":
        # Nothing for the occasion (say, no sport clothes): a casual look beats none.
        looks, ctx = _rank(conn, pid, clean, "casual", wx, day)
        cal = {"occasion": "casual", "reason": "", "events": cal["events"]}
    options = [{"ids": [g["id"] for g in lk["items"]], "score": lk["score"],
                "reasons": lk["reasons"], "warnings": lk["warnings"]} for lk in looks]
    context = {"occasion": ctx.occasion, "temp_low": wx.get("temp_low"), "temp_high": wx.get("temp_high"),
               "temp": wx.get("temp"), "rain": bool(wx.get("rain")), "condition": wx.get("condition"),
               "weather_source": wx.get("source"), "events": cal["events"],
               "occasion_reason": cal["reason"]}
    if not options:
        context["none_reason"] = _why_none(clean)
    # Refresh (or a rebuild of a day without a look) replaces the day's row; a plain build that
    # lost a race to another one keeps the winner's.
    on_conflict = ("DO UPDATE SET options = excluded.options, pick = 0, context = excluded.context, "
                   "updated_at = CURRENT_TIMESTAMP") if replace else "DO NOTHING"
    conn.execute(
        "INSERT INTO daily_looks (profile_id, day, options, pick, context) VALUES (?, ?, ?, 0, ?) "
        f"ON CONFLICT (profile_id, day) {on_conflict}",
        (pid, day, *db.dump("daily_looks", {"options": options, "context": context}).values()))
    return get_row(conn, pid, day)


def _rank(conn, pid: int, clean: list[dict], occasion: str, wx: dict, day: str):
    ctx = matching.Context(occasion=occasion, temp=wx.get("temp"), on=date.fromisoformat(day),
                           last_worn=garments.last_worn_map(conn, pid),
                           look_ratings=garments.look_ratings(conn, pid), rain=bool(wx.get("rain")))
    return matching.suggest(clean, ctx, count=COUNT), ctx


def _events(calendar, profile: dict, day: str) -> list[dict]:
    """The day's calendar events, or [] when they can't be had. Never raises: a broken calendar
    means a casual day, warned about once until the calendar works again."""
    global _calendar_failing
    try:
        evs = calendar(profile, date.fromisoformat(day)) if callable(calendar) else calendar
        if evs is not None and not isinstance(evs, list):
            raise TypeError(f"expected a list, got {type(evs).__name__}")
    except Exception as exc:
        if not _calendar_failing:
            log.warning("Calendar lookup failed (%s: %s); picking today's look for a casual day",
                        type(exc).__name__, exc)
        _calendar_failing = True
        return []
    if _calendar_failing and evs is not None:  # None: nothing was asked
        log.info("Calendar lookup works again")
        _calendar_failing = False
    return evs or []


def _weather(weather, day: str) -> dict:
    """The weather for the day, or {} when it can't be had. Never raises: a broken weather lookup
    means a look without the weather, warned about once until the weather works again."""
    global _weather_failing
    try:
        wx = weather(date.fromisoformat(day)) if callable(weather) else weather
        if wx is not None and not isinstance(wx, dict):
            raise TypeError(f"expected a dict, got {type(wx).__name__}")
    except Exception as exc:
        if not _weather_failing:
            log.warning("Weather lookup failed (%s: %s); picking today's look without the weather",
                        type(exc).__name__, exc)
        _weather_failing = True
        return {}
    if _weather_failing:
        log.info("Weather lookup works again")
        _weather_failing = False
    return wx or {}


def current(conn, profile: dict, day: str | None = None, weather=None, calendar=None) -> dict:
    """Today's row, built when missing or without a look. Weather and calendar default to Home
    Assistant's."""
    return build(conn, profile, day, refresh=False, weather=weather or forecast,
                 calendar=calendar or calendar_events)


def refresh(conn, profile: dict, day: str | None = None, weather=None, calendar=None) -> dict:
    """Build the day again from scratch."""
    return build(conn, profile, day, refresh=True, weather=weather or forecast,
                 calendar=calendar or calendar_events)


def forecast(day: date):
    return ha.forecast(day)


def calendar_events(profile: dict, day: date) -> list[dict] | None:
    """The person's calendar events for the day; None without calendars (Home Assistant isn't asked)."""
    cals = (profile.get("settings") or {}).get("calendars") or []
    if not cals or not config.SUPERVISOR_TOKEN:
        return None
    return ha.calendar_events(cals, day)


def next(conn, profile: dict, day: str | None = None, weather=None) -> dict:  # noqa: A001
    """Show the next option, wrapping round."""
    row = current(conn, profile, day, weather)
    n = len(row["options"])
    if n > 1:
        conn.execute("UPDATE daily_looks SET pick = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                     ((row["pick"] + 1) % n, row["id"]))
        row = get_row(conn, profile["id"], row["day"])
    return row


def wear(conn, profile: dict, day: str | None = None, weather=None) -> tuple[dict, bool]:
    """Log the shown look as worn today. Once a day: returns (row, whether it logged)."""
    row = current(conn, profile, day, weather)
    opt = picked(row)
    if row["worn"] or not opt:
        return row, False
    for g in garments.by_ids(conn, opt["ids"]):
        db.insert(conn, "wears", {"garment_id": g["id"], "worn_on": row["day"]})
    conn.execute("UPDATE daily_looks SET worn = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (row["id"],))
    return get_row(conn, profile["id"], row["day"]), True


def picked(row: dict) -> dict | None:
    opts = row.get("options") or []
    return opts[row["pick"] % len(opts)] if opts else None


# ------------------------------------------------------------------ presenting

def weather_line(ctx: dict) -> str:
    lo, hi = ctx.get("temp_low"), ctx.get("temp_high")
    if lo is None and hi is None:
        return ""
    lo, hi = round(lo if lo is not None else hi), round(hi if hi is not None else lo)
    line = f"{lo} °C" if lo == hi else f"{lo}–{hi} °C"
    return line + (", rain likely" if ctx.get("rain") else "")


def image_name(profile: dict, row: dict) -> str:
    return f"look-{profile_slug(profile)}-{row['day']}-{row['pick']}.jpg"


def _utc_iso(stamp) -> str | None:
    """SQLite's CURRENT_TIMESTAMP (UTC, 'YYYY-MM-DD HH:MM:SS') as ISO 8601 with offset."""
    return f"{stamp.replace(' ', 'T')}+00:00" if stamp else None


def view(conn, profile: dict, row: dict) -> dict:
    """Everything the app, the sensor and the events show about today's look."""
    ctx = row.get("context") or {}
    opt = picked(row)
    items = garments.by_ids(conn, opt["ids"]) if opt else []
    n = len(row.get("options") or [])
    out = {
        "profile_id": profile["id"], "profile": profile["name"], "slug": profile_slug(profile),
        "entity_id": entity_id(profile), "day": row["day"], "worn": bool(row["worn"]),
        "occasion": ctx.get("occasion"), "temp_low": ctx.get("temp_low"), "temp_high": ctx.get("temp_high"),
        "rain": bool(ctx.get("rain")), "condition": ctx.get("condition"), "events": ctx.get("events") or [],
        "weather": weather_line(ctx), "options": n, "pick": row["pick"],
        "generated_at": _utc_iso(row.get("updated_at")),
    }
    if not items:
        reason = ctx.get("none_reason") or "The pieces in this look are gone: refresh to pick again"
        return out | {"state": "none", "summary": "none", "reason": reason, "reasons": [reason],
                      "warnings": [], "items": [], "option": "", "score": None, "image": None}
    names = [g["name"] for g in items]
    summary = ", ".join([names[0]] + [x[:1].lower() + x[1:] for x in names[1:]])
    if len(summary) > MAX_STATE:
        summary = summary[:MAX_STATE - 1].rstrip(", ") + "…"
    reasons = ([ctx["occasion_reason"]] if ctx.get("occasion_reason") else []) + list(opt.get("reasons") or [])
    reasons = reasons[:3]
    return out | {
        "state": summary, "summary": summary, "reason": reasons[0] if reasons else "",
        "reasons": reasons, "warnings": list(opt.get("warnings") or []), "score": opt.get("score"),
        "items": [{"id": g["id"], "name": g["name"], "category": g["category"], "photo": g["photo"]}
                  for g in items],
        "option": f"{row['pick'] % n + 1} of {n}",
        "image": f"{config.HA_MEDIA_URL}/{image_name(profile, row)}",
    }


def profiles(conn) -> list[dict]:
    return db.rows("profiles", conn.execute("SELECT * FROM profiles ORDER BY id"))


def find_profile(conn, ref) -> dict | None:
    """A profile by id, slug or name (case-insensitive)."""
    ref = str(ref if ref is not None else "").strip()
    if not ref:
        return None
    all_profiles = profiles(conn)
    if ref.isdigit():
        hit = [p for p in all_profiles if p["id"] == int(ref)]
        if hit:
            return hit[0]
    low = ref.lower()
    for p in all_profiles:
        if p["name"].lower() == low or profile_slug(p) == low or profile_slug(p) == slug(ref):
            return p
    return None

