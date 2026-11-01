FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    BRIDGE_HTTP_HOST=0.0.0.0 \
    BRIDGE_LAN=1 \
    BRIDGE_PROFILE_ROOT=/data/profiles \
    BRIDGE_SCREENSHOT_ROOT=/data/screenshots \
    BRIDGE_HTTP_PORT=3181 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    XVFB_WHD=1280x800x24 \
    MOZ_DISABLE_CONTENT_SANDBOX=1

RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g; s|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        xvfb x11vnc openbox \
        libgtk-3-0 libnss3 libasound2 libdbus-glib-1-2 libxt6 libx11-xcb1 \
        fonts-liberation fonts-noto-cjk ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-http.txt /app/requirements-http.txt
RUN pip install --no-cache-dir -r /app/requirements-http.txt \
    && python -m camoufox fetch

COPY . /app
RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /data/profiles /data/screenshots

EXPOSE 3181 6080
ENTRYPOINT ["/app/entrypoint.sh"]
