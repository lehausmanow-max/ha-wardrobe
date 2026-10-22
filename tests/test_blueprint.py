"""The morning-look blueprint: loads like Home Assistant loads it, has the four inputs, and holds
nothing personal."""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "blueprints" / "automation" / "wardrobe" / "morning_look.yaml"


class Input(str):
    pass


class Loader(yaml.SafeLoader):
    pass


Loader.add_constructor("!input", lambda loader, node: Input(loader.construct_scalar(node)))


@pytest.fixture(scope="module")
def text():
    return PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def bp(text):
    return yaml.load(text, Loader=Loader)


def test_loads_as_an_automation_blueprint(bp):
    assert bp["blueprint"]["domain"] == "automation"
    assert bp["mode"] == "queued"
    assert bp["triggers"] and bp["actions"]


def test_four_inputs(bp):
    inputs = bp["blueprint"]["input"]
    assert set(inputs) == {"person", "phone", "alarm_sensor", "lead_minutes"}
    assert "text" in inputs["person"]["selector"]
    assert inputs["phone"]["selector"]["device"]["filter"][0]["integration"] == "mobile_app"
    ent = inputs["alarm_sensor"]["selector"]["entity"]["filter"][0]
    assert ent == {"domain": "sensor", "device_class": "timestamp"}
    num = inputs["lead_minutes"]["selector"]["number"]
    assert (num["min"], num["max"], inputs["lead_minutes"]["default"]) == (5, 90, 20)


def test_every_input_is_used(bp, text):
    used = set(re.findall(r"!input\s+(\w+)", text))
    assert used == set(bp["blueprint"]["input"])


def test_no_personal_defaults(bp, text):
    assert "@" not in text
    assert "calendar." not in text
    for name, spec in bp["blueprint"]["input"].items():
        assert name == "lead_minutes" or "default" not in spec, name
    # No HA user IDs (32 hex characters) or phone names baked in.
    assert not re.search(r"\b[0-9a-f]{32}\b", text)
    assert "mobile_app_" in text and not re.search(r"notify\.mobile_app_[a-z0-9]", text)


def test_trigger_uses_trigger_variables(bp):
    assert set(bp["trigger_variables"]) == {"alarm_sensor", "lead_minutes"}
    morning = next(t for t in bp["triggers"] if t.get("id") == "morning")
    assert morning["trigger"] == "template"
    for word in ("alarm_sensor", "lead_minutes", "now()", "18 * 3600"):
        assert word in morning["value_template"]
    button = next(t for t in bp["triggers"] if t.get("id") == "button")
    assert button["event_type"] == "mobile_app_notification_action"


def test_actions_and_events(text):
    for word in ("wardrobe_command", "wardrobe_look_ready", "wardrobe_look_worn", "WARDROBE_WEAR_",
                 "WARDROBE_NEXT_", "Wear this", "Another", "wardrobe-{{ slug }}", "clickAction", "image"):
        assert word in text, word
