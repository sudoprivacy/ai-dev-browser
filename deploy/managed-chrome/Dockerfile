# Shared branded Chrome runtime. Hosts provide authenticated session APIs and
# profile ownership. No display process starts merely by running this image.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl openssl python3 python3-venv xvfb x11vnc websockify novnc \
    && curl -fsSLo /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y /tmp/chrome.deb && rm /tmp/chrome.deb \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 browser && mkdir -p /opt/browser /profile /etc/opt/chrome/policies/managed \
    && python3 -m venv /opt/browser/venv \
    && /opt/browser/venv/bin/pip install --no-cache-dir 'aiohttp>=3.10,<4' 'websockets>=13,<17' \
       'websocket-client>=1,<2' 'Pillow>=10,<13' 'deprecated>=1.2,<2' 'psutil>=5.9,<8'
COPY ai_dev_browser /opt/browser/sdk/ai_dev_browser
COPY deploy/managed-chrome/configure_extension.py /opt/browser/
RUN --mount=type=secret,id=extension_key,required=true python3 /opt/browser/configure_extension.py /run/secrets/extension_key \
    && chown -R browser:browser /profile /opt/browser/extension /home/browser
ENV PYTHONPATH=/opt/browser/sdk
ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/sudoprivacy/ai-dev-browser" \
      org.opencontainers.image.revision=$SOURCE_REVISION
USER browser
WORKDIR /opt/browser
CMD ["/opt/browser/venv/bin/python", "-m", "ai_dev_browser.tools.browser_start", "--help"]
