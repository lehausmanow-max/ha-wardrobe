# Home Assistant base image (Alpine, S6 overlay, bashio), multi-arch.
# Pin a dated tag here once it builds for you, e.g. ghcr.io/home-assistant/base:3.23-2026.05.0
FROM ghcr.io/home-assistant/base:latest

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
