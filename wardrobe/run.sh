#!/command/with-contenv bashio
# shellcheck shell=bash

bashio::log.info "Starting Wardrobe $(bashio::addon.version)"
bashio::log.info "Photo AI: $(bashio::config 'ai_vision_provider'), text AI: $(bashio::config 'ai_text_provider')"

export WARDROBE_DATA_DIR=/data
# Only the Home Assistant Ingress proxy may talk to the app.
export WARDROBE_INGRESS_ONLY=1

cd /app || bashio::exit.nok "App folder missing"
exec /opt/venv/bin/python -m uvicorn wardrobe.main:app \
    --host 0.0.0.0 --port 8099 \
    --no-proxy-headers --no-server-header \
    --log-level warning
