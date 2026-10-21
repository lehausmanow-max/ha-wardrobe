#!/usr/bin/env bash
# Run the app outside Home Assistant for development.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
export WARDROBE_DATA_DIR="${WARDROBE_DATA_DIR:-$here/data}"
# Today's look pictures; under Home Assistant this is /media/wardrobe.
export WARDROBE_HA_MEDIA_DIR="${WARDROBE_HA_MEDIA_DIR:-$WARDROBE_DATA_DIR/ha-media}"
mkdir -p "$WARDROBE_DATA_DIR"
cd "$here/../wardrobe/app"
exec python3 -m uvicorn wardrobe.main:app --host 127.0.0.1 --port "${PORT:-8099}" --reload
