"""Forecast parsing, the rain rules, the fallback to the current temperature, and rain in matching."""

from datetime import date, datetime, timedelta, timezone

import pytest

from wardrobe import config, ha, matching

DAY = date(2026, 10, 21)


def utc_stamp(local_dt: datetime) -> str:
    """A local wall-clock time, written as UTC the way Home Assistant often sends it."""
    return local_dt.astimezone().astimezone(timezone.utc).isoformat()


def entry(day_offset=0, hour=12, **kw):
    when = datetime.combine(DAY + timedelta(days=day_offset), datetime.min.time()).replace(hour=hour)
    return {"datetime": utc_stamp(when), "temperature": 13, "templow": 8, "condition": "cloudy",
            "precipitation_probability": 10, "precipitation": 0} | kw


# ------------------------------------------------------------------ picking today

def test_picks_todays_entry_by_local_date():
    entries = [entry(-1, temperature=20), entry(0), entry(1, temperature=2, templow=-1)]
    f = ha.parse_forecast(entries, DAY)
    assert (f["temp_low"], f["temp_high"], f["temp"]) == (8, 13, 10.5)
    assert f["source"] == "forecast" and f["rain"] is False


@pytest.mark.parametrize("hour", [0, 23])
def test_local_midnight_edges(hour):
    # Just after local midnight and just before the next one both belong to today,
    # even when the UTC timestamp falls on another calendar day.
    entries = [entry(-1, hour=23, temperature=30), entry(0, hour=hour), entry(1, hour=0, temperature=30)]
    assert ha.parse_forecast(entries, DAY)["temp_high"] == 13


def test_naive_and_date_only_stamps():
    assert ha.parse_forecast([{"datetime": "2026-10-21T00:00:00", "temperature": 9, "templow": 4}], DAY)["temp"] == 6.5
    assert ha.parse_forecast([{"datetime": "2026-10-20", "temperature": 9}], DAY) is None


def test_fahrenheit_is_converted():
    f = ha.parse_forecast([entry(0, temperature=50, templow=41)], DAY, unit="°F")
    assert (f["temp_low"], f["temp_high"]) == (5, 10)


def test_missing_low_uses_high():
    f = ha.parse_forecast([entry(0, templow=None)], DAY)
    assert f["temp_low"] == f["temp_high"] == 13


def test_no_entry_for_today():
    assert ha.parse_forecast([entry(1)], DAY) is None
    assert ha.parse_forecast([], DAY) is None


# ------------------------------------------------------------------ rain rules

@pytest.mark.parametrize("kw, rain", [
    ({"precipitation_probability": 50}, True),
    ({"precipitation_probability": 49}, False),
    ({"precipitation": 1}, True),
    ({"precipitation": 0.9}, False),
    ({"condition": "rainy"}, True),
    ({"condition": "pouring"}, True),
    ({"condition": "lightning-rainy"}, True),
    ({"condition": "snowy-rainy"}, True),
    ({"condition": "snowy"}, False),
    ({"condition": "sunny", "precipitation_probability": None, "precipitation": None}, False),
])
def test_rain_rules(kw, rain):
    assert ha.is_rain(entry(0, **kw)) is rain
    assert ha.parse_forecast([entry(0, **kw)], DAY)["rain"] is rain


# ------------------------------------------------------------------ fetching, with HA faked

@pytest.fixture
def fake_ha(monkeypatch):
    calls = []
    replies = {}

    def request(method, path, body=None, timeout=10):
        calls.append((method, path, body))
        r = replies.get((method, path.split("?")[0]))
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(config, "SUPERVISOR_TOKEN", "test-token")
    monkeypatch.setitem(config.OPTIONS, "weather_entity", "weather.test")
    monkeypatch.setattr(ha, "_request", request)
    monkeypatch.setattr(ha, "_cache", {})
    replies[("GET", "/states/weather.test")] = {"state": "rainy", "attributes": {"temperature": 11.4,
                                                                                 "temperature_unit": "°C"}}
    return calls, replies


def test_forecast_reads_service_response(fake_ha):
    calls, replies = fake_ha
    replies[("POST", "/services/weather/get_forecasts")] = {
        "changed_states": [], "service_response": {"weather.test": {"forecast": [entry(0, condition="pouring")]}}}
    f = ha.forecast(DAY)
    assert f["temp"] == 10.5 and f["rain"] is True and f["source"] == "forecast"
    post = next(c for c in calls if c[0] == "POST")
    assert post[1] == "/services/weather/get_forecasts?return_response"
    assert post[2] == {"entity_id": "weather.test", "type": "daily"}
    # Cached: a second call doesn't ask again.
    n = len(calls)
    assert ha.forecast(DAY) == f and len(calls) == n


def test_forecast_falls_back_to_current_temperature(fake_ha):
    _, replies = fake_ha
    replies[("POST", "/services/weather/get_forecasts")] = ha.HAError("HTTP 400")
    f = ha.forecast(DAY)
    assert f["source"] == "current"
    assert f["temp_low"] == f["temp_high"] == f["temp"] == 11.4
    assert f["rain"] is True  # current condition is rainy


def test_forecast_without_daily_entries_falls_back(fake_ha):
    _, replies = fake_ha
    replies[("POST", "/services/weather/get_forecasts")] = {"service_response": {"weather.test": {"forecast": []}}}
    assert ha.forecast(DAY)["source"] == "current"


def test_no_forecast_outside_ha(monkeypatch):
    monkeypatch.setattr(config, "SUPERVISOR_TOKEN", "")
    monkeypatch.setitem(config.OPTIONS, "weather_entity", "weather.test")
    assert ha.forecast(DAY) is None


# ------------------------------------------------------------------ rain in matching

def g(i, name, category, sub="", **kw):
    return {"id": i, "name": name, "category": category, "subcategory": sub, "colors": ["#1f2a44"],
            "pattern": "solid", "formality": 2, "warmth": 2, "status": "active"} | kw


BASE = [g(1, "Navy tee", "top", "t-shirt"), g(2, "Grey chinos", "bottom", "chinos", colors=["#808080"])]


def scored(extra, rain=True, temp=14):
    return matching.score(BASE + extra, matching.Context(temp=temp, rain=rain, on=DAY))


def test_rain_jacket_is_rain_ready():
    s = scored([g(3, "Shell", "outerwear", "rain jacket"), g(4, "Sneakers", "shoes", "sneakers")])
    assert "Rain-ready" in s["reasons"]
    assert not any("Rain likely" in w for w in s["warnings"])


def test_waterproof_note_and_trench_count():
    assert "Rain-ready" in scored([g(3, "Parka", "outerwear", "jacket", notes="Fully WATERPROOF")])["reasons"]
    assert "Rain-ready" in scored([g(3, "Beige trench", "outerwear", "trench")])["reasons"]


def test_no_rain_jacket_warns():
    s = scored([g(3, "Wool coat", "outerwear", "coat")])
    assert "Rain likely: take a rain jacket" in s["warnings"]


def test_suede_and_sandals_warn():
    s = scored([g(3, "Shell", "outerwear", "rain jacket"), g(4, "Desert boots", "shoes", "boots", material="Suede")])
    assert any("Suede" in w for w in s["warnings"])
    s = scored([g(3, "Shell", "outerwear", "rain jacket"), g(4, "Slides", "shoes", "sandals")])
    assert "Sandals in the rain" in s["warnings"]


def test_rain_nudges_are_small_and_off_when_dry():
    jacket = [g(3, "Shell", "outerwear", "rain jacket")]
    dry = scored(jacket, rain=False)
    assert "Rain-ready" not in dry["reasons"] and not any("Rain" in w for w in dry["warnings"])
    wet = scored(jacket)
    assert 0 < wet["parts"]["weather"] - dry["parts"]["weather"] <= 10


def test_suggest_prefers_rain_jacket_when_raining():
    wardrobe = BASE + [g(3, "Shell", "outerwear", "rain jacket"), g(4, "Wool coat", "outerwear", "coat"),
                       g(5, "Sneakers", "shoes", "sneakers", colors=["#f5f5f5"])]
    best = matching.suggest(wardrobe, matching.Context(temp=11, rain=True, on=DAY), count=3)[0]
    assert any(i["id"] == 3 for i in best["items"])
    assert "Rain-ready" in best["reasons"]
