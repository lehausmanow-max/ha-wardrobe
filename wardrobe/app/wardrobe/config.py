"""Runtime configuration: add-on options from /data/options.json plus env overrides."""

import json
import logging
import os
from pathlib import Path

# Set by run.sh from the installed app version; used to cache-bust the UI's CSS and JS.
VERSION = os.environ.get("WARDROBE_VERSION") or "dev"

DATA_DIR = Path(os.environ.get("WARDROBE_DATA_DIR", "/data"))
MEDIA_DIR = DATA_DIR / "media"
THUMB_DIR = MEDIA_DIR / "thumbs"
DB_PATH = DATA_DIR / "wardrobe.db"
OPTIONS_FILE = DATA_DIR / "options.json"
# Home Assistant's media folder (mapped in config.yaml), for the look collages the phone shows.
# Created on first write only; dev and tests point it at a folder under DATA_DIR.
HA_MEDIA_DIR = Path(os.environ.get("WARDROBE_HA_MEDIA_DIR", "/media/wardrobe"))
HA_MEDIA_URL = "/media/local/wardrobe"

DEFAULTS = {
    # Which backend answers text questions (look styling, shopping advice).
    "ai_text_provider": "none",  # none | ollama | claude
    # Which backend looks at photos (auto-tagging, care labels, fit critique).
    "ai_vision_provider": "none",  # none | ollama | claude
    "ollama_url": "http://homeassistant.local:11434",
    "ollama_text_model": "qwen2.5:7b",
    "ollama_vision_model": "qwen2.5vl:7b",
    "claude_api_key": "",
    "claude_model": "claude-sonnet-5-5",
    "weather_entity": "",
    "log_level": "info",
}

log = logging.getLogger("wardrobe")


def load_options() -> dict:
    opts = dict(DEFAULTS)
    if OPTIONS_FILE.exists():
        try:
            opts.update({k: v for k, v in json.loads(OPTIONS_FILE.read_text()).items() if v is not None})
        except (OSError, ValueError) as exc:  # pragma: no cover - defensive
            log.warning("Could not read %s: %s", OPTIONS_FILE, exc)
    # Environment overrides, handy for local development.
    for key in DEFAULTS:
        env_val = os.environ.get(f"WARDROBE_{key.upper()}")
        if env_val is not None:
            opts[key] = env_val
    return opts


OPTIONS = load_options()

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
# When running under the Supervisor, only accept traffic from the Ingress proxy.
INGRESS_ONLY = os.environ.get("WARDROBE_INGRESS_ONLY", "0") == "1"
INGRESS_PROXY_IP = "172.30.32.2"


def ensure_dirs() -> None:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
