"""A wrong weather setting never stops today's look (0.4.1 fix).

On the box, weather_entity was saved as "weather_entity: weather.forecast_home". The space in the
URL made urllib raise http.client.InvalidURL, which wasn't caught, so every publish and command
failed.
"""

import asyncio
import http.client
import logging
import re
import urllib.request
from pathlib import Path

import pytest
import yaml

from wardrobe import config, db, ha, hass, today

ROOT = Path(__file__).resolve().parent.parent
BAD = "weather_entity: weather.forecast_home"

# The Supervisor's grammar for option types (supervisor/apps/options.py, RE_SCHEMA_ELEMENT), trimmed
# to the types this app uses. Options are checked with voluptuous' vol.Match, i.e. re.match.
SUPERVISOR_SCHEMA_ELEMENT = re.compile(
    r"^(?:|bool|email|url|port"
    r"|str(?:\((?P<s_min>\d+)?,(?P<s_max>\d+)?\))?"
    r"|password(?:\((?P<p_min>\d+)?,(?P<p_max>\d+)?\))?"
    r"|match\((?P<match>.*)\)"
    r"|list\((?P<list>.+)\))\??$")


@pytest.fixture
def in_ha(monkeypatch):
    """Running under the Supervisor, with fresh caches and warnings."""
    monkeypatch.setattr(config, "SUPERVISOR_TOKEN", "test-token")
    monkeypatch.setattr(ha, "_cache", {})
    monkeypatch.setattr(ha, "_bad_entity_warned", set(), raising=False)


# ------------------------------------------------------------------ the option's schema

def test_config_yaml_validates_weather_entity():
    cfg = yaml.safe_load((ROOT / "wardrobe" / "config.yaml").read_text(encoding="utf-8"))
    typ = cfg["schema"]["weather_entity"]
    assert typ == r"match(^weather\.[a-z0-9_]+$)?"
    m = SUPERVISOR_SCHEMA_ELEMENT.match(typ)
    assert m, "the Supervisor wouldn't parse this type"
    pattern = m.group("match")
    for value, ok in [("weather.forecast_home", True), ("weather.home2", True), (BAD, False),
                      ("weather.Forecast", False), (" weather.home", False), ("sensor.home", False),
                      ("weather.", False), ("weather.home x", False)]:
        assert bool(re.match(pattern, value)) is ok, value
        # The app's own check agrees with the schema.
        assert bool(ha.WEATHER_ENTITY.fullmatch(value)) is ok, value


# ------------------------------------------------------------------ malformed value = unset

def test_malformed_entity_is_treated_as_unset(in_ha, monkeypatch, caplog):
    monkeypatch.setitem(config.OPTIONS, "weather_entity", BAD)
    monkeypatch.setattr(ha, "_request", lambda *a, **kw: pytest.fail("no request with a malformed entity"))
    with caplog.at_level(logging.WARNING, logger="wardrobe.ha"):
        for _ in range(3):
            assert ha.weather_entity() == ""
            assert ha.weather() is None
            assert ha.forecast() is None
    warnings = [r for r in caplog.records if "weather_entity" in r.getMessage()]
    assert len(warnings) == 1
    assert "weather.forecast_home" in warnings[0].getMessage()


def test_meta_says_weather_not_configured(client, in_ha, monkeypatch):
    monkeypatch.setitem(config.OPTIONS, "weather_entity", BAD)
    assert client.get("/api/meta").json()["weather_configured"] is False
    monkeypatch.setitem(config.OPTIONS, "weather_entity", " weather.forecast_home ")
    assert client.get("/api/meta").json()["weather_configured"] is True


# ------------------------------------------------------------------ _request raises only HAError

def test_request_turns_invalid_url_into_haerror(in_ha):
    # The exact failure from the box: a space in the path. http.client refuses it before connecting.
    with pytest.raises(ha.HAError) as err:
        ha._request("GET", f"/states/{BAD}")
    assert isinstance(err.value.__cause__, http.client.InvalidURL)


@pytest.mark.parametrize("exc", [
    http.client.InvalidURL("bad"), http.client.RemoteDisconnected("gone"), ValueError("unknown url type"),
    UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad byte"), RuntimeError("anything else"),
])
def test_request_turns_any_urlopen_error_into_haerror(in_ha, monkeypatch, exc):
    def boom(*a, **kw):
        raise exc
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(ha.HAError) as err:
        ha._request("POST", "/states/sensor.x", {"state": "x"})
    assert err.value.__cause__ is exc


# ------------------------------------------------------------------ today.build never fails on weather

def test_build_without_weather_when_the_lookup_breaks(client, monkeypatch, caplog):
    monkeypatch.setattr(today, "_weather_failing", False)
    p = client.post("/api/profiles", json={"name": "Sam"}).json()
    with db.connect() as conn:
        for name, cat, col in (("Navy tee", "top", "#1f2a44"), ("Grey chinos", "bottom", "#808080"),
                               ("White sneakers", "shoes", "#f5f5f5")):
            db.insert(conn, "garments", {"profile_id": p["id"], "name": name, "category": cat, "colors": [col]})

    def broken(day):
        raise http.client.InvalidURL("URL can't contain control characters")

    with caplog.at_level(logging.WARNING, logger="wardrobe.today"), db.connect() as conn:
        row = today.current(conn, p, "2026-10-22", broken)
        row = today.build(conn, p, "2026-10-22", refresh=True, weather=broken)
        row = today.build(conn, p, "2026-10-22", refresh=True, weather=lambda d: "not a dict")
    assert row["options"], "a look is still built"
    assert row["context"]["temp"] is None and row["context"]["rain"] is False
    assert caplog.text.count("Weather lookup failed") == 1  # once, not per build
    # Working again: no more warnings, and the next failure is reported anew.
    with caplog.at_level(logging.WARNING, logger="wardrobe.today"), db.connect() as conn:
        today.build(conn, p, "2026-10-22", refresh=True, weather=lambda d: {"temp": 10})
        assert today._weather_failing is False
        today.build(conn, p, "2026-10-22", refresh=True, weather=broken)
    assert caplog.text.count("Weather lookup failed") == 2


def test_today_endpoint_survives_malformed_setting(client, in_ha, monkeypatch):
    """The box's case end to end: real ha.forecast, malformed option, no network."""
    monkeypatch.setitem(config.OPTIONS, "weather_entity", BAD)
    p = client.post("/api/profiles", json={"name": "Sam"}).json()
    r = client.get("/api/today", params={"profile_id": p["id"]})
    assert r.status_code == 200 and r.json()["state"] == "none"  # empty wardrobe, but no crash


# ------------------------------------------------------------------ dispatch catches _command errors

class FakeHA:
    def __init__(self):
        self.states, self.events = [], []

    def set_state(self, entity_id, state, attributes):
        self.states.append(entity_id)

    def fire_event(self, event_type, data):
        self.events.append(event_type)


def test_dispatch_logs_command_errors_and_carries_on(client, monkeypatch, caplog):
    client.post("/api/profiles", json={"name": "Sam"})
    monkeypatch.setattr(today, "forecast", lambda day: None)
    fake = FakeHA()
    real = hass.Bridge._command
    calls = []

    def flaky(self, ref, action):
        calls.append(action)
        if len(calls) == 1:
            raise http.client.InvalidURL("URL can't contain control characters")
        return real(self, ref, action)

    monkeypatch.setattr(hass.Bridge, "_command", flaky)

    async def scenario():
        b = hass.Bridge(client=fake, token="t")
        first = await b.dispatch({"profile": "sam", "action": "prepare"})
        second = await b.dispatch({"profile": "sam", "action": "prepare"})  # the lock was released
        return first, second

    with caplog.at_level(logging.ERROR, logger="wardrobe.hass"):
        first, second = asyncio.run(asyncio.wait_for(scenario(), 20))
    assert (first, second) == (False, True)
    assert "wardrobe_command prepare for 'sam' failed" in caplog.text
    assert "InvalidURL" in caplog.text  # with the traceback
    assert fake.states == ["sensor.wardrobe_today_sam"] and fake.events == ["wardrobe_look_ready"]
