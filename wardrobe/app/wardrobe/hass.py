"""The bridge to Home Assistant: listens for wardrobe_command events over the WebSocket API and
publishes today's look as a sensor plus events over REST.

Home Assistant decides when and where a look is shown; this module only answers commands and keeps
the sensors current. It runs only under the Supervisor. A Home Assistant problem is logged once
per outage and retried; it never breaks the app.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from websockets.asyncio.client import connect

from . import collage, config, db, ha, today

log = logging.getLogger("wardrobe.hass")
WS_URL = "ws://supervisor/core/websocket"
COMMAND = "wardrobe_command"
LOOK_READY = "wardrobe_look_ready"
LOOK_WORN = "wardrobe_look_worn"
ACTIONS = ("prepare", "next", "wear", "refresh")
DAILY_HOUR = 4


class BridgeError(Exception):
    pass


class RestClient:
    """The real Home Assistant, over REST. Blocking; the bridge calls it from a thread."""

    def set_state(self, entity_id: str, state: str, attributes: dict) -> None:
        ha.set_state(entity_id, state, attributes)

    def fire_event(self, event_type: str, data: dict) -> None:
        ha.fire_event(event_type, data)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sensor_attributes(v: dict) -> dict:
    return {
        "friendly_name": f"Wardrobe today: {v['profile']}", "icon": "mdi:hanger",
        "profile_id": v["profile_id"], "profile": v["profile"],
        "items": [{k: i[k] for k in ("id", "name", "category")} for i in v["items"]],
        "reasons": v["reasons"][:3], "warnings": v["warnings"], "occasion": v["occasion"],
        "temp_low": v["temp_low"], "temp_high": v["temp_high"], "rain": v["rain"], "condition": v["condition"],
        "events": v["events"], "option": v["option"], "worn": v["worn"],
        "image": v["image"], "entity_picture": v["image"], "generated_at": v["generated_at"],
    }


def event_data(event_type: str, v: dict) -> dict:
    if event_type == LOOK_WORN:
        return {"profile_id": v["profile_id"], "profile": v["profile"], "slug": v["slug"],
                "items": [{k: i[k] for k in ("id", "name", "category")} for i in v["items"]]}
    return {"profile_id": v["profile_id"], "profile": v["profile"], "slug": v["slug"],
            "entity_id": v["entity_id"], "summary": v["summary"], "reason": v["reason"],
            "image": v["image"], "option": v["option"], "options": v["options"]}


class Bridge:
    def __init__(self, client=None, ws_url: str = WS_URL, token: str | None = None,
                 backoff: tuple[float, float] = (2, 60), retry_every: float = 60):
        self.client = client or RestClient()
        self.ws_url = ws_url
        self.token = token if token is not None else config.SUPERVISOR_TOKEN
        self.backoff = backoff
        self.retry_every = retry_every
        self.connected = False
        self.since: str | None = None
        self.last_error: str | None = None
        self._ws_down = False
        self._rest_down = False
        self._pending: set[int] = set()
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        now = datetime.now()
        self._daily_done = now.date() if now.hour >= DAILY_HOUR else now.date() - timedelta(days=1)

    # ---------------------------------------------------------------- status

    def status(self) -> dict:
        return {"enabled": True, "connected": self.connected, "since": self.since, "last_error": self.last_error}

    def _ws_problem(self, msg: str) -> None:
        self.last_error = msg
        if not self._ws_down:
            log.warning("Home Assistant connection: %s. Retrying in the background.", msg)
            self._ws_down = True

    def _rest_problem(self, msg: str) -> None:
        self.last_error = msg
        if not self._rest_down:
            log.warning("Publishing to Home Assistant failed: %s. Will retry.", msg)
            self._rest_down = True

    def spawn(self, coro) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # ---------------------------------------------------------------- WebSocket

    async def run(self) -> None:
        """Stay connected: authenticate, subscribe, handle commands; reconnect with backoff."""
        delay = self.backoff[0]
        while True:
            try:
                await self._session()
                delay = self.backoff[0]
                self._ws_problem("connection closed")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # anything from the network or Home Assistant
                if self.connected:
                    delay = self.backoff[0]
                self._ws_problem(str(exc) or type(exc).__name__)
            self.connected = False
            await asyncio.sleep(delay)
            delay = min(delay * 2, self.backoff[1])

    async def _session(self) -> None:
        async with connect(self.ws_url, max_size=None, open_timeout=10) as ws:
            first = json.loads(await ws.recv())
            if first.get("type") != "auth_required":
                raise BridgeError(f"unexpected first message {first.get('type')!r}")
            await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
            reply = json.loads(await ws.recv())
            if reply.get("type") != "auth_ok":
                raise BridgeError(f"authentication failed ({reply.get('message') or reply.get('type')})")
            await ws.send(json.dumps({"id": 1, "type": "subscribe_events", "event_type": COMMAND}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == 1 and msg.get("type") == "result":
                    if not msg.get("success"):
                        raise BridgeError(f"subscribe failed: {msg.get('error')}")
                    break
            self.connected, self.since, self.last_error = True, _now(), None
            if self._ws_down:
                log.info("Home Assistant connection back")
            else:
                log.info("Connected to Home Assistant")
            self._ws_down = False
            # States set through the API are gone after a Home Assistant restart: set them again.
            self.spawn(self.publish_all())
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                event = msg.get("event") or {}
                if msg.get("type") == "event" and event.get("event_type") == COMMAND:
                    self.spawn(self.dispatch(event.get("data") or {}))

    # ---------------------------------------------------------------- commands

    async def dispatch(self, data: dict) -> bool:
        """Handle one wardrobe_command. Returns whether it did anything."""
        action = str(data.get("action") or "").strip().lower()
        ref = data.get("profile")
        if action not in ACTIONS:
            log.warning("wardrobe_command: unknown action %r (use %s)", action, ", ".join(ACTIONS))
            return False
        async with self._lock:
            pid = await asyncio.to_thread(self._command, ref, action)
            if pid is None:
                log.warning("wardrobe_command: no profile %r", ref)
                return False
            await self.publish(pid, LOOK_WORN if action == "wear" else LOOK_READY)
        return True

    def _command(self, ref, action: str) -> int | None:
        with db.connect() as conn:
            p = today.find_profile(conn, ref)
            if not p:
                return None
            if action == "prepare":
                today.current(conn, p)
            elif action == "next":
                today.next(conn, p)
            elif action == "wear":
                today.wear(conn, p)
            elif action == "refresh":
                today.build(conn, p, refresh=True, weather=today.forecast)
            return p["id"]

    # ---------------------------------------------------------------- publishing

    def _view(self, pid: int) -> dict | None:
        with db.connect() as conn:
            p = today.find_profile(conn, pid)
            if not p:
                return None
            row = today.current(conn, p)
            v = today.view(conn, p, row)
            if v["items"]:
                try:
                    if not collage.make(v["items"], today.image_name(p, row)):
                        v["image"] = None
                except OSError as exc:
                    log.warning("Couldn't write the look picture: %s", exc)
                    v["image"] = None
            return v

    def _publish_sync(self, pid: int, event_type: str | None) -> None:
        v = self._view(pid)
        if v is None:
            self._pending.discard(pid)
            return
        self.client.set_state(v["entity_id"], v["state"], sensor_attributes(v))
        if event_type:
            self.client.fire_event(event_type, event_data(event_type, v))

    async def publish(self, pid: int, event_type: str | None = None) -> bool:
        """Set the person's sensor, and fire the event when given. Failures are retried later
        (the sensor only; an event belongs to its moment)."""
        try:
            await asyncio.to_thread(self._publish_sync, pid, event_type)
        except ha.HAError as exc:
            self._pending.add(pid)
            self._rest_problem(str(exc))
            return False
        except Exception:
            self._pending.add(pid)
            log.exception("Publishing today's look failed")
            return False
        self._pending.discard(pid)
        if self._rest_down:
            log.info("Publishing to Home Assistant works again")
            self._rest_down = False
        return True

    async def publish_all(self) -> None:
        def ids():
            with db.connect() as conn:
                return [p["id"] for p in today.profiles(conn)]
        for pid in await asyncio.to_thread(ids):
            await self.publish(pid)

    # ---------------------------------------------------------------- housekeeping

    async def maintain(self) -> None:
        """Every so often: retry failed publishes; once a day at 04:00, the new day's look."""
        while True:
            await asyncio.sleep(self.retry_every)
            try:
                await self.tick(datetime.now())
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Wardrobe housekeeping failed")

    async def tick(self, now: datetime) -> None:
        if now.hour >= DAILY_HOUR and self._daily_done != now.date():
            self._daily_done = now.date()
            await asyncio.to_thread(collage.cleanup, now.date())
            self._pending.clear()
            await self.publish_all()
        elif self._pending and self.connected:
            for pid in list(self._pending):
                await self.publish(pid)


# -------------------------------------------------------------------- app wiring

bridge: Bridge | None = None
_tasks: list[asyncio.Task] = []


def status() -> dict:
    if bridge is None:
        return {"enabled": False, "connected": False, "since": None, "last_error": None}
    return bridge.status()


async def start() -> None:
    global bridge
    if not config.SUPERVISOR_TOKEN:
        log.info("Not running under Home Assistant: no sensors or commands")
        return
    bridge = Bridge()
    loop = asyncio.get_running_loop()
    _tasks[:] = [loop.create_task(bridge.run()), loop.create_task(bridge.maintain())]


async def stop() -> None:
    global bridge
    for t in _tasks:
        t.cancel()
    await asyncio.gather(*_tasks, return_exceptions=True)
    _tasks.clear()
    bridge = None


def notify_app_change(pid: int, event_type: str) -> None:
    """A look changed in the app: publish it to Home Assistant in the background."""
    if bridge is not None:
        bridge.spawn(bridge.publish(pid, event_type))
