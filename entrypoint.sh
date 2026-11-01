#!/bin/bash
set -e
export DISPLAY="${DISPLAY:-:99}"
export BRIDGE_HTTP_HOST="${BRIDGE_HTTP_HOST:-0.0.0.0}"
export BRIDGE_HTTP_PORT="${BRIDGE_HTTP_PORT:-3181}"

echo "[Bridge] starting Xvfb on $DISPLAY"
Xvfb "$DISPLAY" -screen 0 "${XVFB_WHD:-1280x800x24}" -ac +extension GLX +render -noreset &
sleep 0.5
openbox >/tmp/openbox.log 2>&1 &

# x11vnc 只监听容器内 127.0.0.1，由 websockify 转给 noVNC；必须设 VNC 口令，没设就不起画面
if [ -n "${BRIDGE_VNC_PASSWORD:-}" ]; then
  mkdir -p "$HOME/.vnc"
  x11vnc -storepasswd "$BRIDGE_VNC_PASSWORD" "$HOME/.vnc/passwd" >/dev/null 2>&1
  chmod 600 "$HOME/.vnc/passwd"
  unset BRIDGE_VNC_PASSWORD
  x11vnc -display "$DISPLAY" -rfbport 5900 -rfbauth "$HOME/.vnc/passwd" -forever -shared -localhost >/tmp/x11vnc.log 2>&1 &
  websockify --web /app/vendor/novnc 6080 127.0.0.1:5900 >/tmp/novnc.log 2>&1 &
  echo "[Bridge] noVNC :6080  HTTP :$BRIDGE_HTTP_PORT"
else
  echo "[Bridge] BRIDGE_VNC_PASSWORD 未设置：不启动 x11vnc 和 noVNC，只起 HTTP :$BRIDGE_HTTP_PORT" >&2
fi
exec python /app/run_http.py
