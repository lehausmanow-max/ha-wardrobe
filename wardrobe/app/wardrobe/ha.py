"""Small bridge to Home Assistant over REST: current user (Ingress headers), weather, forecast,
and setting states and firing events. Everything here is blocking; call it from a thread."""

import json
import logging
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


class HAError(Exception):
    pass


def ingress_user(headers) -> dict:
    return {
        "id": headers.get("x-remote-user-id", ""),
        "name": headers.get("x-remote-user-name", ""),
        "display_name": headers.get("x-remote-user-display-name", ""),
    }


def _request(method: str, path: str, body=None, timeout: float = 10):
    """Call the Home Assistant REST API through the Supervisor proxy. Raises HAError."""
    if not config.SUPERVISOR_TOKEN:
        raise HAError("Not running under Home Assistant")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers={
        "Authorization": f"Bearer {config.SUPERVISOR_TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as exc:
        raise HAError(f"{method} {path}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise HAError(f"{method} {path}: {exc}") from exc
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
    entity = (config.OPTIONS.get("weather_entity") or "").strip()
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
    entity = (config.OPTIONS.get("weather_entity") or "").strip()
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


def set_state(entity_id: str, state: str, attributes: dict) -> None:
    _request("POST", f"/states/{entity_id}", {"state": state, "attributes": attributes})


def fire_event(event_type: str, data: dict) -> None:
    _request("POST", f"/events/{event_type}", data)

