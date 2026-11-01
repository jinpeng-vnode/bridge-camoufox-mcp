"""给账号池用的普通 HTTP，不走 MCP。鉴权、Host、CORS 都交给 security.Gate 这一个关口。"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("bridge")


def make_server(host: str, port: int, runner, gate):
    """建好服务但不开始监听循环；gate 由调用方在启动前用 build_gate 建好。"""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            log.info("%s %s", self.address_string(), fmt % args)

        def _json(self, code, obj, extra=()):
            raw = json.dumps(obj, ensure_ascii=False).encode("utf-8") if obj is not None else b""
            self.send_response(code)
            for key, value in extra:
                self.send_header(key, value)
            if obj is not None:
                self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(raw)


        def _read_json(self) -> dict:
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
            except ValueError:
                return {}
            if length <= 0:
                return {}
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            return data if isinstance(data, dict) else {}

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_HEAD(self):
            self._dispatch("GET")

        def do_OPTIONS(self):
            self._dispatch("OPTIONS")

        def _dispatch(self, method):
            path = self.path.split("?", 1)[0]
            verdict = gate.evaluate(method, path, dict(self.headers.items()))
            cors = verdict.headers
            if verdict.status is not None:
                self._json(verdict.status, None if verdict.status == 204 else {"error": verdict.error}, cors)
                return
            if path == "/health":
                self._json(200, {"ok": True}, cors)
                return
            try:
                payload = self._read_json() if method == "POST" else {}
                result = _route(method, path, payload, runner)
                if result is None:
                    self._json(404, {"error": "not found"}, cors)
                    return
                self._json(200, result, cors)
            except ValueError as exc:
                self._json(400, {"error": str(exc)}, cors)
            except RuntimeError as exc:
                self._json(409, {"error": str(exc)}, cors)
            except Exception as exc:  # noqa: BLE001
                log.exception("HTTP 处理失败")
                self._json(500, {"error": str(exc)}, cors)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def start_http_server(host: str, port: int, runner, gate):
    server = make_server(host, port, runner, gate)
    log.info("浏览器 HTTP 监听 %s:%s", host, port)
    server.serve_forever()


def _route(method: str, path: str, payload: dict, runner):
    if method == "POST" and path == "/v1/sessions":
        return runner(
            "launch",
            {
                "account_id": str(payload.get("account_id") or ""),
                "user_data_dir": str(payload.get("user_data_dir") or ""),
                "proxy_server": str(payload.get("proxy_server") or ""),
                "locale": str(payload.get("locale") or ""),
                "humanize": bool(payload.get("humanize", True)),
                "geoip": bool(payload.get("geoip", False)),
            },
            timeout=90,
        )
    if method == "GET" and path == "/v1/sessions/current":
        return runner("status", {}, timeout=15)
    if method == "POST" and path == "/v1/sessions/current/close":
        return runner("close", {}, timeout=30)
    mapping = {
        "/v1/sessions/current/goto": ("goto", {"url": str(payload.get("url") or "")}),
        "/v1/sessions/current/click": ("click", {"selector": str(payload.get("selector") or "")}),
        "/v1/sessions/current/fill": (
            "fill",
            {"selector": str(payload.get("selector") or ""), "value": str(payload.get("value") or "")},
        ),
        "/v1/sessions/current/press": ("press_key", {"key": str(payload.get("key") or "")}),
        "/v1/sessions/current/screenshot": (
            "screenshot",
            {"path": str(payload.get("path") or ""), "full_page": bool(payload.get("full_page", False))},
        ),
    }
    if method == "POST" and path in mapping:
        name, args = mapping[path]
        return runner(name, args, timeout=60)
    return None
