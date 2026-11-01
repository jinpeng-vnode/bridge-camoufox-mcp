"""关口：启动检查、令牌、Host、CORS、导航地址；HTTP 和 ASGI 两个入口都实际发请求走一遍。"""

from __future__ import annotations

import http.client
import json
import os
import sys
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from http_api import make_server  # noqa: E402
from security import StartupError, asgi_guard, build_gate, check_navigation_url  # noqa: E402

TOKEN = "t0ken-for-test"


# ---------- 启动检查 ----------

def test_lan_without_token_refuses_start():
    with pytest.raises(StartupError):
        build_gate("0.0.0.0", 3181, {"BRIDGE_LAN": "1"})


def test_non_loopback_without_lan_refuses_start():
    with pytest.raises(StartupError):
        build_gate("0.0.0.0", 3181, {"BRIDGE_TOKEN": TOKEN})


def test_loopback_without_token_allowed():
    gate = build_gate("127.0.0.1", 3181, {})
    assert gate.evaluate("GET", "/v1/sessions/current", {"Host": "127.0.0.1:3181"}).status is None


def test_lan_with_token_starts():
    gate = build_gate("0.0.0.0", 3181, {"BRIDGE_LAN": "1", "BRIDGE_TOKEN": TOKEN})
    assert gate.token == TOKEN


# ---------- 判断规则 ----------

@pytest.fixture
def gate():
    env = {
        "BRIDGE_LAN": "1",
        "BRIDGE_TOKEN": TOKEN,
        "BRIDGE_ALLOWED_HOSTS": "browser:3181, lanbox",
        "BRIDGE_CORS_ORIGINS": "http://127.0.0.1:8810",
    }
    return build_gate("0.0.0.0", 3181, env)


AUTH = {"Authorization": "Bearer " + TOKEN}


@pytest.mark.parametrize(
    "host,ok",
    [
        ("127.0.0.1:3181", True),
        ("localhost:3181", True),
        ("[::1]:3181", True),
        ("browser:3181", True),
        ("lanbox:9999", True),
        ("127.0.0.1:9999", False),
        ("browser:80", False),
        ("evil.example.com", False),
        ("", False),
    ],
)
def test_host_rule(gate, host, ok):
    verdict = gate.evaluate("GET", "/x", dict(AUTH, Host=host))
    assert (verdict.status is None) == ok
    if not ok:
        assert verdict.status == 421


def test_token_rule(gate):
    base = {"Host": "browser:3181"}
    assert gate.evaluate("GET", "/x", base).status == 401
    assert gate.evaluate("GET", "/x", dict(base, Authorization="Bearer wrong")).status == 401
    assert gate.evaluate("GET", "/x", dict(base, **AUTH)).status is None
    assert gate.evaluate("GET", "/health", base).status is None


def test_cors_rule(gate):
    base = dict(AUTH, Host="127.0.0.1:3181")
    good = gate.evaluate("POST", "/x", dict(base, Origin="http://127.0.0.1:8810"))
    assert good.status is None
    assert ("Access-Control-Allow-Origin", "http://127.0.0.1:8810") in good.headers
    assert gate.evaluate("POST", "/x", dict(base, Origin="http://evil.example.com")).status == 403
    no_origin = gate.evaluate("POST", "/x", base)
    assert not any(k == "Access-Control-Allow-Origin" for k, _ in no_origin.headers)
    pre = gate.evaluate("OPTIONS", "/x", {"Host": "127.0.0.1:3181", "Origin": "http://127.0.0.1:8810"})
    assert pre.status == 204


@pytest.mark.parametrize("url", ["https://example.com/a", "http://127.0.0.1:8810/", "about:blank"])
def test_navigation_allowed(url):
    assert check_navigation_url(url) == url


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "FILE:///C:/Windows/win.ini", "javascript:alert(1)", "about:config",
     "chrome://settings", "data:text/html,x", "view-source:https://a.com", "", "http://", "example.com"],
)
def test_navigation_rejected(url):
    with pytest.raises(ValueError):
        check_navigation_url(url)


# ---------- 账号池 HTTP 实际发请求 ----------

@pytest.fixture
def http_server(gate):
    calls = []

    def runner(name, args, timeout=60):
        calls.append((name, args))
        if name == "goto":
            args["url"] = check_navigation_url(args["url"])
        return {"ok": True, "name": name}

    server = make_server("127.0.0.1", 0, runner, gate)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], calls
    server.shutdown()
    server.server_close()


def _request(port, method, path, headers, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    raw = json.dumps(body).encode("utf-8") if body is not None else None
    conn.request(method, path, body=raw, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, dict(resp.getheaders()), data


def test_http_gate_end_to_end(http_server):
    port, calls = http_server
    ok_host = {"Host": "browser:3181"}
    assert _request(port, "GET", "/health", ok_host)[0] == 200
    assert _request(port, "GET", "/v1/sessions/current", ok_host)[0] == 401
    assert _request(port, "GET", "/v1/sessions/current", {"Host": "evil:3181", **AUTH})[0] == 421
    assert calls == []
    status, _, _ = _request(port, "GET", "/v1/sessions/current", dict(ok_host, **AUTH))
    assert status == 200 and calls[-1][0] == "status"
    status, headers, _ = _request(
        port, "POST", "/v1/sessions/current/close",
        dict(ok_host, Origin="http://127.0.0.1:8810", **AUTH), {},
    )
    assert status == 200 and headers.get("Access-Control-Allow-Origin") == "http://127.0.0.1:8810"
    assert _request(port, "POST", "/v1/sessions/current/close", dict(ok_host, Origin="http://x.com", **AUTH), {})[0] == 403
    status, _, data = _request(
        port, "POST", "/v1/sessions/current/goto", dict(ok_host, **AUTH), {"url": "file:///etc/passwd"}
    )
    assert status == 400 and "http" in json.loads(data)["error"]


# ---------- MCP 入口（ASGI）实际发请求 ----------

def test_asgi_gate_end_to_end(gate):
    from starlette.testclient import TestClient

    hits = []

    async def app(scope, receive, send):
        hits.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"ok"})

    client = TestClient(asgi_guard(app, gate), base_url="http://browser:3181")
    assert client.post("/mcp").status_code == 401
    assert client.post("/mcp", headers={"Host": "evil.example.com", **AUTH}).status_code == 421
    assert hits == []
    resp = client.post("/mcp", headers={"Origin": "http://127.0.0.1:8810", **AUTH})
    assert resp.status_code == 200 and resp.headers["access-control-allow-origin"] == "http://127.0.0.1:8810"
    assert client.options("/mcp", headers={"Origin": "http://127.0.0.1:8810"}).status_code == 204
    assert hits == ["/mcp"]
