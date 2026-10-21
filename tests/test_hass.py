"""The Home Assistant bridge: command dispatch against a fake HA, publishing and retries, and the
WebSocket session against a local fake server (auth, subscribe, a command, reconnect)."""

import asyncio
import json
import logging
from datetime import datetime, timedelta

import pytest
from websockets.asyncio.server import serve

from wardrobe import db, ha, hass, today

DRY = {"temp_low": 12, "temp_high": 16, "temp": 14, "rain": False, "condition": "cloudy", "source": "forecast"}


class FakeHA:
    """Records the states and events it's given; can be told to fail."""

    def __init__(self):
        self.states, self.events, self.fail = [], [], False

    def set_state(self, entity_id, state, attributes):
        if self.fail:
            raise ha.HAError("HA is down")
        self.states.append((entity_id, state, attributes))

    def fire_event(self, event_type, data):
        if self.fail:
            raise ha.HAError("HA is down")
        self.events.append((event_type, data))


@pytest.fixture
def people(client, monkeypatch):
    monkeypatch.setattr(today, "forecast", lambda day: DRY)
    out = {}
    for name in ("Sam", "Anna B."):
        p = client.post("/api/profiles", json={"name": name}).json()
        with db.connect() as conn:
            for g in (("Navy tee", "top", "#1f2a44"), ("White shirt", "top", "#f5f5f5"),
                      ("Grey chinos", "bottom", "#808080"), ("Blue jeans", "bottom", "#34507a"),
                      ("White sneakers", "shoes", "#f5f5f5")):
                db.insert(conn, "garments", {"profile_id": p["id"], "name": g[0], "category": g[1], "colors": [g[2]],
                                             "formality": 2, "warmth": 2})
        out[name] = p
    return out


def run(coro, timeout=20):
    async def guarded():
        return await asyncio.wait_for(coro, timeout)
    return asyncio.run(guarded())


async def dispatch_all(fake, *commands):
    b = hass.Bridge(client=fake, token="t")
    results = [await b.dispatch(c) for c in commands]
    return b, results


# ------------------------------------------------------------------ dispatch

def test_prepare_publishes_sensor_and_ready_event(people):
    fake = FakeHA()
    _, ok = run(dispatch_all(fake, {"profile": "sam", "action": "prepare"}))
    assert ok == [True]
    (entity, state, attrs), = fake.states
    assert entity == "sensor.wardrobe_today_sam"
    assert state != "none" and len(state) <= 255
    assert attrs["friendly_name"] == "Wardrobe today: Sam" and attrs["icon"] == "mdi:hanger"
    assert attrs["profile_id"] == people["Sam"]["id"] and attrs["profile"] == "Sam"
    assert set(attrs) >= {"items", "reasons", "warnings", "occasion", "temp_low", "temp_high", "rain", "condition",
                          "events", "option", "worn", "image", "entity_picture", "generated_at"}
    assert attrs["items"] and set(attrs["items"][0]) == {"id", "name", "category"}
    assert attrs["temp_low"] == 12 and attrs["occasion"] == "casual" and attrs["events"] == []
    assert attrs["option"].startswith("1 of ")
    (etype, data), = fake.events
    assert etype == "wardrobe_look_ready"
    assert set(data) == {"profile_id", "profile", "slug", "entity_id", "summary", "reason", "image", "option", "options"}
    assert data["slug"] == "sam" and data["summary"] == state and data["entity_id"] == entity


def test_next_wear_refresh(people):
    fake = FakeHA()
    run(dispatch_all(fake,
                     {"profile": "Anna B.", "action": "prepare"},
                     {"profile": "anna_b", "action": "next"},
                     {"profile": str(people["Anna B."]["id"]), "action": "wear"},
                     {"profile": "anna_b", "action": "wear"},
                     {"profile": "ANNA_B", "action": "refresh"}))
    options = [s[2]["option"] for s in fake.states]
    assert options[0].startswith("1 of ") and options[1].startswith("2 of ")
    assert [e[0] for e in fake.events] == ["wardrobe_look_ready", "wardrobe_look_ready", "wardrobe_look_worn",
                                           "wardrobe_look_worn", "wardrobe_look_ready"]
    worn = fake.events[2][1]
    assert set(worn) == {"profile_id", "profile", "slug", "items"} and worn["slug"] == "anna_b"
    assert fake.states[2][2]["worn"] is True
    assert fake.states[4][2]["option"].startswith("1 of ") and fake.states[4][2]["worn"] is True
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wears").fetchone()[0] == len(worn["items"])


def test_unknown_profile_or_action_does_nothing(people, caplog):
    fake = FakeHA()
    with caplog.at_level(logging.WARNING, logger="wardrobe.hass"):
        _, ok = run(dispatch_all(fake, {"profile": "nobody", "action": "next"},
                                 {"profile": "sam", "action": "dance"}, {"action": "next"}))
    assert ok == [False, False, False]
    assert fake.states == [] and fake.events == []
    assert "no profile 'nobody'" in caplog.text and "unknown action 'dance'" in caplog.text


def test_failed_publish_is_logged_once_and_retried(people, caplog):
    fake = FakeHA()
    fake.fail = True

    async def scenario():
        b = hass.Bridge(client=fake, token="t")
        with caplog.at_level(logging.WARNING, logger="wardrobe.hass"):
            await b.dispatch({"profile": "sam", "action": "prepare"})
            await b.dispatch({"profile": "sam", "action": "next"})
        assert b._pending == {people["Sam"]["id"]} and "HA is down" in b.last_error
        fake.fail = False
        b.connected = True
        await b.tick(datetime.now().replace(hour=12))
        assert not b._pending
        return b

    run(scenario())
    assert caplog.text.count("Publishing to Home Assistant failed") == 1
    assert len(fake.states) == 1 and fake.states[0][2]["option"].startswith("2 of ")
    assert fake.events == []  # events belong to their moment and aren't replayed


def test_daily_tick_publishes_everyone_once(people):
    fake = FakeHA()

    async def scenario():
        b = hass.Bridge(client=fake, token="t")
        b._daily_done = datetime.now().date() - timedelta(days=1)
        await b.tick(datetime.now().replace(hour=3))  # before 04:00: nothing
        assert fake.states == []
        await b.tick(datetime.now().replace(hour=4, minute=0))
        await b.tick(datetime.now().replace(hour=4, minute=1))  # once a day

    run(scenario())
    assert sorted(s[0] for s in fake.states) == ["sensor.wardrobe_today_anna_b", "sensor.wardrobe_today_sam"]
    assert fake.events == []


def test_app_endpoints_publish_when_bridge_runs(client, people, monkeypatch):
    calls = []
    monkeypatch.setattr(hass, "notify_app_change", lambda pid, ev: calls.append((pid, ev)))
    pid = people["Sam"]["id"]
    client.post("/api/today/next", json={"profile_id": pid})
    client.post("/api/today/wear", json={"profile_id": pid})
    assert calls == [(pid, "wardrobe_look_ready"), (pid, "wardrobe_look_worn")]


def test_notify_is_a_no_op_without_bridge():
    assert hass.bridge is None
    hass.notify_app_change(1, hass.LOOK_READY)


# ------------------------------------------------------------------ WebSocket session

async def wait_for(cond, timeout=5.0):
    end = asyncio.get_running_loop().time() + timeout
    while not cond():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("timed out")
        await asyncio.sleep(0.01)


def test_bridge_handshake_command_and_reconnect(people):
    fake = FakeHA()
    received, sessions = [], []

    async def handler(ws):
        sessions.append(ws)
        await ws.send(json.dumps({"type": "auth_required", "ha_version": "2026.10.0"}))
        received.append(json.loads(await ws.recv()))
        await ws.send(json.dumps({"type": "auth_ok", "ha_version": "2026.10.0"}))
        received.append(json.loads(await ws.recv()))
        await ws.send(json.dumps({"id": 1, "type": "result", "success": True, "result": None}))
        if len(sessions) == 1:
            await ws.send(json.dumps({"id": 1, "type": "event", "event": {
                "event_type": "wardrobe_command", "data": {"profile": "sam", "action": "next"}}}))
            await wait_for(lambda: any(e[0] == "wardrobe_look_ready" for e in fake.events))
            await ws.close()  # Home Assistant restarts
        else:
            await ws.wait_closed()  # stay connected until the bridge goes

    async def scenario():
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            b = hass.Bridge(client=fake, ws_url=f"ws://127.0.0.1:{port}", token="secret-token",
                            backoff=(0.05, 0.2))
            task = asyncio.create_task(b.run())
            try:
                await wait_for(lambda: len(sessions) == 2 and b.connected)
                await wait_for(lambda: len(fake.states) >= 5)
                status = b.status()
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            return status

    status = run(scenario())
    assert received[0] == {"type": "auth", "access_token": "secret-token"}
    assert received[1] == {"id": 1, "type": "subscribe_events", "event_type": "wardrobe_command"}
    assert received[2:] == received[:2]  # the same handshake after reconnecting
    assert status["connected"] is True and status["since"] and status["last_error"] is None
    # On each connect every profile's sensor is set; the command fired one ready event.
    entities = [s[0] for s in fake.states]
    assert entities.count("sensor.wardrobe_today_sam") >= 3 and entities.count("sensor.wardrobe_today_anna_b") >= 2
    assert [e[0] for e in fake.events] == ["wardrobe_look_ready"]
    assert fake.events[0][1]["option"].startswith("2 of ")


def test_bridge_reports_auth_failure(people):
    async def handler(ws):
        await ws.send(json.dumps({"type": "auth_required"}))
        await ws.recv()
        await ws.send(json.dumps({"type": "auth_invalid", "message": "Invalid access token"}))
        await ws.close()

    async def scenario():
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            b = hass.Bridge(client=FakeHA(), ws_url=f"ws://127.0.0.1:{port}", token="bad", backoff=(0.05, 0.1))
            task = asyncio.create_task(b.run())
            try:
                await wait_for(lambda: b.last_error is not None)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            return b.status()

    status = run(scenario())
    assert status["connected"] is False and "authentication failed" in status["last_error"]


def test_bridge_survives_unreachable_home_assistant(caplog, monkeypatch):
    attempts = []

    def refused(*args, **kw):
        attempts.append(1)
        raise OSError("Connect call failed")

    monkeypatch.setattr(hass, "connect", refused)

    async def scenario():
        b = hass.Bridge(client=FakeHA(), token="t", backoff=(0.01, 0.02))
        with caplog.at_level(logging.WARNING, logger="wardrobe.hass"):
            task = asyncio.create_task(b.run())
            await wait_for(lambda: len(attempts) >= 4)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return b

    b = run(scenario())
    assert not b.connected and "Connect call failed" in b.last_error
    assert caplog.text.count("Home Assistant connection") == 1  # once per outage, not per attempt
