"""Small bridge to Home Assistant over REST: current user (Ingress headers), weather, forecast,
and setting states and firing events. Everything here is blocking; call it from a thread."""

import json
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime

from . import config

log = logging.getLogger("wardrobe.ha")
_cache: dict = {}
BASE = "http://supervisor/core/api"
FORECAST_TTL = 30 * 60
RAINY = {"rainy", "pouring", "lightning-rainy", "snowy-rainy"}
# Same rule as the weather_entity schema in config.yaml.
WEATHER_ENTITY = re.compile(r"weather\.[a-z0-9_]+")
_bad_entity_warned: set[str] = set()


class HAError(Exception):
    pass


def ingress_user(headers) -> dict:
    return {
        "id": headers.get("x-remote-user-id", ""),
        "name": headers.get("x-remote-user-name", ""),
        "display_name": headers.get("x-remote-user-display-name", ""),
    }


def weather_entity() -> str:
    """The configured weather entity, or "" when it's unset or isn't an entity ID like
    weather.forecast_home. A malformed value is warned about once and otherwise ignored."""
    raw = config.OPTIONS.get("weather_entity")
    entity = str(raw or "").strip()
    if not entity or WEATHER_ENTITY.fullmatch(entity):
        return entity
    if entity not in _bad_entity_warned:
        _bad_entity_warned.add(entity)
        log.warning("Ignoring the weather_entity option %r: it must be an entity ID such as "
                    "weather.forecast_home. Looks are picked without the weather until it's fixed.", raw)
    return ""


def _request(method: str, path: str, body=None, timeout: float = 10):
    """Call the Home Assistant REST API through the Supervisor proxy. Raises HAError, and only that."""
    if not config.SUPERVISOR_TOKEN:
        raise HAError("Not running under Home Assistant")
    try:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers={
            "Authorization": f"Bearer {config.SUPERVISOR_TOKEN}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as exc:
        raise HAError(f"{method} {path}: HTTP {exc.code}") from exc
    except Exception as exc:  # URLError, OSError, http.client.InvalidURL, ValueError, ...
        raise HAError(f"{method} {path}: {type(exc).__name__}: {exc}") from exc
    try:
        return json.loads(raw) if raw else None
    except ValueError as exc:
        raise HAError(f"{method} {path}: reply isn't JSON") from exc


def _celsius(value, unit) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return (v - 32) * 5 / 9 if unit == "°F" else v


def weather() -> dict | None:
    entity = weather_entity()
    if not entity or not config.SUPERVISOR_TOKEN:
        return None
    hit = _cache.get(entity)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    try:
        state = _request("GET", f"/states/{entity}", timeout=5) or {}
    except HAError as exc:
        log.warning("Weather lookup for %s failed: %s", entity, exc)
        return None
    attrs = state.get("attributes", {})
    unit = attrs.get("temperature_unit", "°C")
    temp = _celsius(attrs.get("temperature"), unit)
    data = {"entity": entity, "condition": state.get("state"), "temperature": temp, "unit": unit,
            "wind_speed": attrs.get("wind_speed"), "humidity": attrs.get("humidity")}
    _cache[entity] = (time.time(), data)
    return data


def is_rain(entry: dict) -> bool:
    """Rain counts when it's likely (≥ 50 %), wet (≥ 1 mm) or the condition says so."""
    def num(k):
        try:
            return float(entry.get(k))
        except (TypeError, ValueError):
            return 0.0
    return (num("precipitation_probability") >= 50 or num("precipitation") >= 1
            or entry.get("condition") in RAINY)


def _local_day(stamp) -> date | None:
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt.astimezone() if dt.tzinfo else dt).date()


def parse_forecast(entries, day: date, unit: str = "°C") -> dict | None:
    """Today's entry of a daily forecast, by local date."""
    for e in entries or []:
        if not isinstance(e, dict) or _local_day(e.get("datetime")) != day:
            continue
        hi = _celsius(e.get("temperature"), unit)
        lo = _celsius(e.get("templow"), unit)
        if hi is None and lo is None:
            continue
        lo = hi if lo is None else lo
        hi = lo if hi is None else hi
        return {"temp_low": round(lo, 1), "temp_high": round(hi, 1), "temp": round((lo + hi) / 2, 1),
                "condition": e.get("condition"), "rain": is_rain(e),
                "precipitation_probability": e.get("precipitation_probability"),
                "precipitation": e.get("precipitation"), "source": "forecast"}
    return None


def _from_current(w: dict | None) -> dict | None:
    if not w or w.get("temperature") is None:
        return None
    t = round(w["temperature"], 1)
    return {"temp_low": t, "temp_high": t, "temp": t, "condition": w.get("condition"),
            "rain": w.get("condition") in RAINY, "precipitation_probability": None,
            "precipitation": None, "source": "current"}


def forecast(day: date | None = None) -> dict | None:
    """Today's low, high and rain from the weather entity's daily forecast; the current
    temperature when there's no daily forecast. None without a weather entity or HA."""
    entity = weather_entity()
    if not entity or not config.SUPERVISOR_TOKEN:
        return None
    day = day or date.today()
    key = ("forecast", entity, day.isoformat())
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < FORECAST_TTL:
        return hit[1]
    result = None
    try:
        reply = _request("POST", "/services/weather/get_forecasts?return_response",
                         {"entity_id": entity, "type": "daily"}) or {}
        entries = ((reply.get("service_response") or {}).get(entity) or {}).get("forecast") or []
        unit = (weather() or {}).get("unit") or "°C"
        result = parse_forecast(entries, day, unit)
    except HAError as exc:
        log.info("No daily forecast from %s (%s); using the current temperature", entity, exc)
    if result is None:
        result = _from_current(weather())
    if result is not None:
        _cache[key] = (time.time(), result)
    return result


def calendars() -> list[dict]:
    """Home Assistant's calendar entities: [{entity_id, name}], by name. Raises HAError."""
    states = _request("GET", "/states") or []
    out = [{"entity_id": s["entity_id"],
            "name": (s.get("attributes") or {}).get("friendly_name") or s["entity_id"]}
           for s in states if isinstance(s, dict) and str(s.get("entity_id", "")).startswith("calendar.")]
    return sorted(out, key=lambda c: c["name"].lower())


def _event_start(raw) -> tuple[object, bool]:
    """An event's start as (date or aware datetime, all_day)."""
    if isinstance(raw, dict):  # some integrations answer {"date": ...} or {"dateTime": ...}
        raw = raw.get("dateTime") or raw.get("date")
    s = str(raw or "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return date.fromisoformat(s), True
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")), False
    except ValueError:
        return None, False


def calendar_events(entity_ids: list[str], day: date) -> list[dict]:
    """The day's events from the given calendars: [{calendar, summary, start, all_day}],
    where start is a date for all-day events. Raises HAError."""
    if not entity_ids:
        return []
    start = datetime(day.year, day.month, day.day).astimezone()
    end = datetime.fromordinal(day.toordinal() + 1).astimezone()
    reply = _request("POST", "/services/calendar/get_events?return_response", {
        "entity_id": list(entity_ids), "start_date_time": start.isoformat(),
        "end_date_time": end.isoformat()}) or {}
    response = reply.get("service_response") if isinstance(reply, dict) else None
    if not isinstance(response, dict):
        raise HAError("calendar.get_events: no service_response in the reply")
    out = []
    for cal in entity_ids:
        for ev in (response.get(cal) or {}).get("events") or []:
            if not isinstance(ev, dict):
                continue
            when, all_day = _event_start(ev.get("start"))
            out.append({"calendar": cal, "summary": str(ev.get("summary") or ""), "start": when,
                        "all_day": all_day})
    return out


def set_state(entity_id: str, state: str, attributes: dict) -> None:
    _request("POST", f"/states/{entity_id}", {"state": state, "attributes": attributes})


def fire_event(event_type: str, data: dict) -> None:
    _request("POST", f"/events/{event_type}", data)

