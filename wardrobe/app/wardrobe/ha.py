"""Small bridge to Home Assistant: current user (from Ingress headers) and weather."""

import json
import logging
import time
import urllib.error
import urllib.request

from . import config

log = logging.getLogger("wardrobe.ha")
_cache: dict = {}


def ingress_user(headers) -> dict:
    return {
        "id": headers.get("x-remote-user-id", ""),
        "name": headers.get("x-remote-user-name", ""),
        "display_name": headers.get("x-remote-user-display-name", ""),
    }


def weather() -> dict | None:
    entity = (config.OPTIONS.get("weather_entity") or "").strip()
    if not entity or not config.SUPERVISOR_TOKEN:
        return None
    hit = _cache.get(entity)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    req = urllib.request.Request(
        f"http://supervisor/core/api/states/{entity}",
        headers={"Authorization": f"Bearer {config.SUPERVISOR_TOKEN}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            state = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.warning("Weather lookup for %s failed: %s", entity, exc)
        return None
    attrs = state.get("attributes", {})
    temp = attrs.get("temperature")
    unit = attrs.get("temperature_unit", "°C")
    try:
        temp = float(temp)
        if unit == "°F":
            temp = (temp - 32) * 5 / 9
    except (TypeError, ValueError):
        temp = None
    data = {"entity": entity, "condition": state.get("state"), "temperature": temp,
            "wind_speed": attrs.get("wind_speed"), "humidity": attrs.get("humidity")}
    _cache[entity] = (time.time(), data)
    return data
