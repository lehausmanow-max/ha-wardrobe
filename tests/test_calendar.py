"""The calendar decides the occasion of today's look: whole-word matching in English and Dutch,
all-day events, the most formal match, errors; ha.calendar_events parsing; settings validation."""

import logging
from datetime import date, datetime

import pytest

from wardrobe import agenda, config, db, ha, today
from test_today import DAY, wardrobe, weather

WORDS = agenda.words_for({})


def ev(summary, start="2026-10-21T19:00:00", all_day=False):
    s = date.fromisoformat(start) if all_day else datetime.fromisoformat(start)
    return {"calendar": "calendar.test", "summary": summary, "start": s, "all_day": all_day}


@pytest.fixture
def sam(client):
    return client.post("/api/profiles", json={"name": "Sam"}).json()


@pytest.fixture(autouse=True)
def fresh_flags(monkeypatch):
    monkeypatch.setattr(today, "_calendar_failing", False)


# ------------------------------------------------------------------ matching

@pytest.mark.parametrize("summary,occasion", [
    ("Dinner with friends", "evening"),
    ("Etentje bij Jan", "evening"),
    ("DINER", "evening"),
    ("Op kantoor", "work"),
    ("Kantoor", "work"),
    ("Werkdag Utrecht", "work"),
    ("Sollicitatie", "smart"),
    ("Client meeting", "smart"),
    ("Padel", "sport"),
    ("Hardlopen in het park", "sport"),
    ("Dinnerware shopping", None),       # whole words only
    ("Kantoortuin opruimen", None),
    ("Running errands", None),           # "run" isn't "running"
    ("Coffee", None),
])
def test_whole_words_dutch_and_english(summary, occasion):
    assert agenda.occasion_of(summary, WORDS) == occasion


def test_multi_word_phrase_spans_whitespace():
    words = {"work": ["on site"]}
    assert agenda.occasion_of("Visit on   site", words) == "work"
    assert agenda.occasion_of("Onsite visit", words) is None


def test_most_formal_match_wins():
    m = agenda.match([ev("Gym", "2026-10-21T07:00:00"), ev("Kantoor", "2026-10-21T09:00:00"),
                      ev("Diner", "2026-10-21T19:00:00"), ev("Dentist", "2026-10-21T11:00:00")], WORDS)
    assert m["occasion"] == "evening"
    assert m["reason"] == "Diner at 19:00 in your calendar"
    # Only the events that matched, in time order, with summary and time only.
    assert m["events"] == [{"summary": "Gym", "time": "07:00"}, {"summary": "Kantoor", "time": "09:00"},
                           {"summary": "Diner", "time": "19:00"}]


def test_equal_rank_goes_to_the_earlier_event():
    m = agenda.match([ev("Concert", "2026-10-21T20:00:00"), ev("Interview", "2026-10-21T10:00:00")], WORDS)
    assert m["occasion"] == "smart" and m["reason"].startswith("Interview at 10:00")


def test_all_day_event():
    m = agenda.match([ev("Kantoor", "2026-10-21", all_day=True)], WORDS)
    assert m == {"occasion": "work", "reason": "Kantoor today",
                 "events": [{"summary": "Kantoor", "time": "all day"}]}


def test_no_events_is_casual():
    assert agenda.match([], WORDS) == {"occasion": "casual", "reason": "", "events": []}


def test_own_words_replace_defaults_per_occasion():
    words = agenda.words_for({"words": {"sport": ["klimmen"]}})
    assert words["sport"] == ["klimmen"] and words["work"] == agenda.DEFAULT_WORDS["work"]
    assert agenda.occasion_of("Klimmen", words) == "sport"
    assert agenda.occasion_of("Gym", words) is None


# ------------------------------------------------------------------ Home Assistant's reply

def test_calendar_events_parses_service_response(monkeypatch):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"changed_states": [], "service_response": {
            "calendar.a": {"events": [
                {"start": "2026-10-21T19:00:00+02:00", "end": "2026-10-21T22:00:00+02:00", "summary": "Diner"},
                {"start": "2026-10-21", "end": "2026-10-22", "summary": "Kantoor"}]},
            "calendar.b": {"events": []}}}
    monkeypatch.setattr(ha, "_request", fake)
    out = ha.calendar_events(["calendar.a", "calendar.b"], date(2026, 10, 21))
    assert seen["method"] == "POST"
    assert seen["path"] == "/services/calendar/get_events?return_response"
    assert seen["body"]["entity_id"] == ["calendar.a", "calendar.b"]
    start = datetime.fromisoformat(seen["body"]["start_date_time"])
    end = datetime.fromisoformat(seen["body"]["end_date_time"])
    assert start.tzinfo and start.date() == date(2026, 10, 21) and start.hour == 0
    assert end.date() == date(2026, 10, 22) and end.hour == 0
    assert [(e["calendar"], e["summary"], e["all_day"]) for e in out] == [
        ("calendar.a", "Diner", False), ("calendar.a", "Kantoor", True)]
    assert out[1]["start"] == date(2026, 10, 21)
    m = agenda.match(out, WORDS)
    assert m["occasion"] == "evening"


def test_calendar_events_without_service_response_is_an_error(monkeypatch):
    monkeypatch.setattr(ha, "_request", lambda *a, **k: {"changed_states": []})
    with pytest.raises(ha.HAError):
        ha.calendar_events(["calendar.a"], date(2026, 10, 21))


def test_calendars_lists_only_calendar_entities(monkeypatch):
    monkeypatch.setattr(ha, "_request", lambda *a, **k: [
        {"entity_id": "calendar.work", "attributes": {"friendly_name": "Work"}},
        {"entity_id": "sensor.x", "attributes": {}},
        {"entity_id": "calendar.agenda", "attributes": {}}])
    assert ha.calendars() == [{"entity_id": "calendar.agenda", "name": "calendar.agenda"},
                              {"entity_id": "calendar.work", "name": "Work"}]


# ------------------------------------------------------------------ today's look

def test_build_uses_the_calendar(sam):
    with db.connect() as conn:
        wardrobe(conn, sam["id"])
        row = today.current(conn, sam, DAY, weather, calendar=lambda p, d: [ev("Diner")])
        assert row["context"]["occasion"] == "evening"
        assert row["context"]["events"] == [{"summary": "Diner", "time": "19:00"}]
        v = today.view(conn, sam, row)
        assert v["occasion"] == "evening"
        assert v["reasons"][0] == "Diner at 19:00 in your calendar" == v["reason"]
        assert len(v["reasons"]) <= 3
        assert v["events"] == [{"summary": "Diner", "time": "19:00"}]


def test_no_calendars_is_casual_without_asking_ha(sam, monkeypatch):
    monkeypatch.setattr(ha, "calendar_events", lambda *a: pytest.fail("asked Home Assistant"))
    with db.connect() as conn:
        wardrobe(conn, sam["id"])
        row = today.current(conn, sam, DAY, weather)
        assert row["context"]["occasion"] == "casual" and row["context"]["events"] == []


def test_calendar_error_gives_casual_and_one_warning(sam, monkeypatch, caplog):
    def broken(ids, day):
        raise ha.HAError("POST /services/calendar/get_events: HTTP 500")
    monkeypatch.setattr(ha, "calendar_events", broken)
    monkeypatch.setattr(config, "SUPERVISOR_TOKEN", "t")
    profile = sam | {"settings": {"calendars": ["calendar.test"]}}
    caplog.set_level(logging.WARNING, logger="wardrobe.today")
    with db.connect() as conn:
        wardrobe(conn, sam["id"])
        row = today.current(conn, profile, DAY, weather)
        assert row["context"]["occasion"] == "casual" and row["options"]
        today.build(conn, profile, DAY, refresh=True, weather=weather)
    warnings = [r for r in caplog.records if "Calendar lookup failed" in r.getMessage()]
    assert len(warnings) == 1


def test_occasion_without_clothes_falls_back_to_casual(sam, monkeypatch):
    import wardrobe.matching as matching
    real = matching.suggest

    def picky(garments, ctx, *a, **k):
        return [] if ctx.occasion == "sport" else real(garments, ctx, *a, **k)
    monkeypatch.setattr(matching, "suggest", picky)
    with db.connect() as conn:
        wardrobe(conn, sam["id"])
        row = today.current(conn, sam, DAY, weather, calendar=lambda p, d: [ev("Gym")])
        assert row["options"] and row["context"]["occasion"] == "casual"
        assert row["context"]["occasion_reason"] == ""


def test_settings_calendars_reach_the_ha_call(sam, monkeypatch):
    asked = {}

    def fake(ids, day):
        asked["ids"] = ids
        return [ev("Kantoor", "2026-10-21", all_day=True)]
    monkeypatch.setattr(ha, "calendar_events", fake)
    monkeypatch.setattr(config, "SUPERVISOR_TOKEN", "t")
    with db.connect() as conn:
        wardrobe(conn, sam["id"])
        db.update(conn, "profiles", sam["id"], {"settings": {"calendars": ["calendar.sam"]}})
        p = today.find_profile(conn, sam["id"])
        row = today.current(conn, p, DAY, weather)
    assert asked["ids"] == ["calendar.sam"]
    assert row["context"]["occasion"] == "work" and row["context"]["occasion_reason"] == "Kantoor today"


# ------------------------------------------------------------------ settings

def put(client, pid, **data):
    return client.put(f"/api/profiles/{pid}", json=data)


def test_settings_save_calendars_and_words(client, sam):
    r = put(client, sam["id"], calendars=["calendar.sam", "calendar.sam", " calendar.shared "],
            words={"work": " office ,  op   kantoor,, Office ", "sport": ["gym", "x" * 60]})
    assert r.status_code == 200, r.text
    s = r.json()["settings"]
    assert s["calendars"] == ["calendar.sam", "calendar.shared"]
    assert s["words"]["work"] == ["office", "op kantoor"]
    assert s["words"]["sport"] == ["gym", "x" * 40]
    assert s["words"]["evening"] == agenda.DEFAULT_WORDS["evening"]  # untouched lists keep defaults

    # Other settings survive, and words: null resets to the defaults.
    r = put(client, sam["id"], words=None)
    s = r.json()["settings"]
    assert "words" not in s and s["calendars"] == ["calendar.sam", "calendar.shared"]


@pytest.mark.parametrize("bad", [["sensor.x"], ["calendar.Bad"], ["calendar."], ["calendar.a b"], "calendar.a"])
def test_settings_reject_non_calendar_ids(client, sam, bad):
    r = put(client, sam["id"], calendars=bad)
    assert r.status_code == 400


def test_settings_word_limits(client, sam):
    r = put(client, sam["id"], words={"smart": [f"w{i}" for i in range(60)]})
    assert len(r.json()["settings"]["words"]["smart"]) == 40
    assert put(client, sam["id"], words="gym").status_code == 400


def test_calendar_endpoint_outside_ha(client):
    r = client.get("/api/ha/calendars")
    assert r.status_code == 200 and r.json()["available"] is False


def test_calendar_endpoint_in_ha(client, monkeypatch):
    monkeypatch.setattr(config, "SUPERVISOR_TOKEN", "t")
    monkeypatch.setattr(ha, "calendars", lambda: [{"entity_id": "calendar.a", "name": "A"}])
    assert client.get("/api/ha/calendars").json() == {
        "available": True, "calendars": [{"entity_id": "calendar.a", "name": "A"}], "error": None}


def test_meta_has_default_words_and_sensor(client, sam):
    m = client.get("/api/meta").json()
    assert m["calendar_words_default"]["work"][:2] == ["office", "kantoor"]
    p = next(p for p in m["profiles"] if p["id"] == sam["id"])
    assert p["slug"] == "sam" and p["entity_id"] == "sensor.wardrobe_today_sam"


def test_outside_ha_calendars_are_not_asked(sam, monkeypatch, caplog):
    monkeypatch.setattr(ha, "calendar_events", lambda *a: pytest.fail("asked Home Assistant"))
    profile = sam | {"settings": {"calendars": ["calendar.test"]}}
    with db.connect() as conn:
        wardrobe(conn, sam["id"])
        row = today.current(conn, profile, DAY, weather)
    assert row["context"]["occasion"] == "casual"
    assert "Calendar lookup failed" not in caplog.text
