"""The day's calendar as an occasion: words in event titles decide what today's look dresses for.

Calendars and words are per person, in profiles.settings. Pure functions; Home Assistant is
asked in ha.calendar_events().
"""

import re
from datetime import date, datetime

OCCASIONS = ("work", "smart", "evening", "sport")
DEFAULT_WORDS = {
    "work": ["office", "kantoor", "op kantoor", "on site", "werkdag"],
    "smart": ["interview", "sollicitatie", "presentation", "presentatie", "client", "klant", "wedding",
              "bruiloft", "funeral", "uitvaart", "ceremony"],
    "evening": ["dinner", "diner", "etentje", "theatre", "theater", "concert", "party", "feest", "borrel"],
    "sport": ["gym", "sportschool", "training", "run", "hardlopen", "padel", "tennis", "yoga", "zwemmen"],
}
# Most formal first; evening and smart are equal, and then the earlier event wins.
RANK = {"evening": 3, "smart": 3, "work": 2, "sport": 1}
CALENDAR_ID = re.compile(r"calendar\.[a-z0-9_]+")
MAX_WORDS = 40
MAX_WORD_LEN = 40
MAX_CALENDARS = 20


# ------------------------------------------------------------------ settings

def words_for(settings: dict | None) -> dict[str, list[str]]:
    """The person's words per occasion; the defaults where none are stored."""
    stored = (settings or {}).get("words") or {}
    return {occ: list(stored[occ]) if isinstance(stored.get(occ), list) else list(DEFAULT_WORDS[occ])
            for occ in OCCASIONS}


def _word_list(raw) -> list[str]:
    parts = raw.split(",") if isinstance(raw, str) else raw if isinstance(raw, list) else None
    if parts is None:
        raise ValueError("Words must be a comma-separated text or a list")
    out = []
    for p in parts:
        w = " ".join(str(p if p is not None else "").split())[:MAX_WORD_LEN].strip()
        if w and w.lower() not in (x.lower() for x in out):
            out.append(w)
    return out[:MAX_WORDS]


def clean_settings(data: dict) -> dict:
    """The calendar settings from a request: only calendar.* IDs, words trimmed and capped.
    Returns only the keys present in data. Raises ValueError on a bad value."""
    out = {}
    if "calendars" in data:
        raw = data["calendars"] or []
        if not isinstance(raw, list):
            raise ValueError("calendars must be a list of calendar entity IDs")
        cals = []
        for c in raw:
            c = str(c or "").strip()
            if not CALENDAR_ID.fullmatch(c):
                raise ValueError(f"Not a calendar entity ID: {c[:60]!r}")
            if c not in cals:
                cals.append(c)
        out["calendars"] = cals[:MAX_CALENDARS]
    if "words" in data:
        raw = data["words"]
        if raw is None:
            out["words"] = None  # back to the defaults
        elif not isinstance(raw, dict):
            raise ValueError("words must map work, smart, evening and sport to words")
        else:
            out["words"] = {occ: _word_list(raw[occ]) for occ in OCCASIONS if occ in raw}
    return out


def apply_settings(settings: dict | None, cleaned: dict) -> dict:
    """Merge cleaned calendar settings into a profile's settings."""
    s = dict(settings or {})
    if "calendars" in cleaned:
        s["calendars"] = cleaned["calendars"]
    if "words" in cleaned:
        if cleaned["words"] is None:
            s.pop("words", None)
        else:
            s["words"] = words_for(s) | cleaned["words"]
    return s


# ------------------------------------------------------------------ matching

def _pattern(word: str) -> re.Pattern:
    body = r"\s+".join(re.escape(p) for p in word.split())
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def occasion_of(summary: str, words: dict[str, list[str]]) -> str | None:
    """The most formal occasion whose words appear in the summary as whole words."""
    best = None
    for occ in OCCASIONS:
        if any(_pattern(w).search(summary or "") for w in words.get(occ) or []):
            if best is None or RANK[occ] > RANK[best]:
                best = occ
    return best


def _start(ev: dict) -> datetime | None:
    """An event's start in local time, without a timezone, so all events compare."""
    s = ev.get("start")
    if isinstance(s, datetime):
        dt = s
    elif isinstance(s, date):
        return datetime(s.year, s.month, s.day)
    else:
        try:
            dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


def _time(ev: dict) -> str:
    if ev.get("all_day"):
        return "all day"
    dt = _start(ev)
    return dt.strftime("%H:%M") if dt else ""


def _title(summary: str) -> str:
    s = " ".join((summary or "").split())
    return s if len(s) <= 60 else s[:59].rstrip() + "…"


def match(events: list[dict], words: dict[str, list[str]]) -> dict:
    """The day's occasion from its events: {occasion, reason, events}. Casual when nothing matches."""
    hits = []
    for ev in events or []:
        occ = occasion_of(ev.get("summary") or "", words)
        if occ:
            hits.append((occ, ev))
    if not hits:
        return {"occasion": "casual", "reason": "", "events": []}
    # All-day events sort first in the day: they start at 00:00.
    hits.sort(key=lambda h: (-RANK[h[0]], _start(h[1]) or datetime.max))
    occ, ev = hits[0]
    title = _title(ev.get("summary"))
    reason = f"{title} today" if ev.get("all_day") else f"{title} at {_time(ev)} in your calendar"
    used = sorted(hits, key=lambda h: _start(h[1]) or datetime.max)
    return {"occasion": occ, "reason": reason,
            "events": [{"summary": _title(e.get("summary")), "time": _time(e)} for _, e in used]}
