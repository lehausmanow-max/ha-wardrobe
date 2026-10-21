"""Test setup: the app runs against a temporary data folder, with no AI and no Home Assistant."""

import os
import tempfile

# config.py reads these at import and main.py runs db.init() at import,
# so they must be set before anything from the app is imported.
os.environ["WARDROBE_DATA_DIR"] = tempfile.mkdtemp(prefix="wardrobe-test-")
os.environ["WARDROBE_AI_TEXT_PROVIDER"] = "none"
os.environ["WARDROBE_AI_VISION_PROVIDER"] = "none"
for name in ("WARDROBE_INGRESS_ONLY", "SUPERVISOR_TOKEN", "WARDROBE_CLAUDE_API_KEY"):
    os.environ.pop(name, None)

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from wardrobe import config, db, main  # noqa: E402


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A fresh, empty data folder for each test."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path / "media")
    monkeypatch.setattr(config, "THUMB_DIR", tmp_path / "media" / "thumbs")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "wardrobe.db")
    return tmp_path


@pytest.fixture
def client(data_dir):
    db.init()
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def profile(client):
    r = client.post("/api/profiles", json={"name": "Alex"})
    assert r.status_code == 201, r.text
    return r.json()
