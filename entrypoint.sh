#!/bin/bash
set -e
export DISPLAY="${DISPLAY:-:99}"
export BRIDGE_HTTP_HOST="${BRIDGE_HTTP_HOST:-0.0.0.0}"
export BRIDGE_HTTP_PORT="${BRIDGE_HTTP_PORT:-3181}"

echo "[Bridge] starting Xvfb on $DISPLAY"
Xvfb "$DISPLAY" -screen 0 "${XVFB_WHD:-1280x800x24}" -ac +extension GLX +render -noreset &
sleep 0.5
openbox >/tmp/openbox.log 2>&1 &
x11vnc -display "$DISPLAY" -rfbport 5900 -nopw -forever -shared -listen 0.0.0.0 >/tmp/x11vnc.log 2>&1 &
websockify --web /app/vendor/novnc 6080 127.0.0.1:5900 >/tmp/novnc.log 2>&1 &
echo "[Bridge] noVNC :6080  HTTP :$BRIDGE_HTTP_PORT"
exec python /app/run_http.py
