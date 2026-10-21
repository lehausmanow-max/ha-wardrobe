# Home Assistant base image (Alpine, S6 overlay, bashio), multi-arch.
# Pinned, so an update of the base image never lands unannounced. Alpine 3.24 ships Python 3.14:
# when changing this, update PYTHON_VERSION in .github/workflows/check.yml to match.
FROM ghcr.io/home-assistant/base:3.24-2026.08.0

ARG BUILD_VERSION=0.1.0

# Pillow from Alpine avoids compiling it on a Raspberry Pi.
RUN apk add --no-cache python3 py3-pip py3-pillow

WORKDIR /app
COPY app/requirements.txt /app/requirements.txt
RUN python3 -m venv --system-site-packages /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt

COPY app/ /app/
COPY run.sh /run.sh
RUN chmod a+x /run.sh

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="aarch64|amd64"

CMD [ "/run.sh" ]
