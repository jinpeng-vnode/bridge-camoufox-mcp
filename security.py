"""唯一的请求关口：监听检查、令牌、Host 头、CORS 白名单，另带导航地址校验。

MCP（main.py）和账号池 HTTP（http_api.py）都只在这里做判断，各条路由里不再另写校验。

环境变量：
    BRIDGE_LAN=1            允许监听非本机地址；此时必须设 BRIDGE_TOKEN，否则拒绝启动
    BRIDGE_TOKEN            Bearer 令牌；设了就校验（/health 除外）
    BRIDGE_ALLOWED_HOSTS    追加放行的 Host，逗号分隔；写 host:port 只放行该端口，只写 host 放行任意端口
    BRIDGE_CORS_ORIGINS     放行的跨域来源，逗号分隔，如 http://127.0.0.1:8810；默认不放行任何来源
"""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

LOOPBACK = ("127.0.0.1", "localhost", "::1")
OPEN_PATHS = ("/health",)
PREFLIGHT_HEADERS = [
    ("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS"),
    ("Access-Control-Allow-Headers", "Authorization, Content-Type, Mcp-Session-Id, Mcp-Protocol-Version"),
    ("Access-Control-Max-Age", "600"),
]


class StartupError(RuntimeError):
    """配置不安全，拒绝启动。"""


def _split(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _host_key(host: str) -> str:
    host = host.strip().lower()
    # 只给裸 IPv6（多个冒号）加方括号；host:port 原样保留
    return "[%s]" % host if host.count(":") > 1 and not host.startswith("[") else host


@dataclass(frozen=True)
class Verdict:
    status: int | None  # None = 放行
    error: str = ""
    headers: list = field(default_factory=list)


@dataclass(frozen=True)
class Gate:
    token: str
    allowed_hosts: frozenset
    cors_origins: frozenset

    def host_allowed(self, host_header: str) -> bool:
        value = (host_header or "").strip().lower()
        if not value:
            return False
        if value in self.allowed_hosts:
            return True
        if value.startswith("["):
            name = value.split("]", 1)[0] + "]"
        else:
            name = value.rsplit(":", 1)[0] if ":" in value else value
        return name in self.allowed_hosts

    def token_ok(self, authorization: str) -> bool:
        if not self.token:
            return True
        expected = ("Bearer %s" % self.token).encode("utf-8")
        return hmac.compare_digest((authorization or "").encode("utf-8"), expected)

    def evaluate(self, method: str, path: str, headers: dict) -> Verdict:
        h = {str(k).lower(): str(v) for k, v in headers.items()}
        if not self.host_allowed(h.get("host", "")):
            return Verdict(421, "host not allowed")
        origin = h.get("origin", "")
        cors: list = []
        if origin:
            if origin not in self.cors_origins:
                return Verdict(403, "origin not allowed")
            cors = [
                ("Access-Control-Allow-Origin", origin),
                ("Access-Control-Expose-Headers", "Mcp-Session-Id"),
                ("Vary", "Origin"),
            ]
        if method.upper() == "OPTIONS":
            return Verdict(204, "", cors + (PREFLIGHT_HEADERS if origin else []))
        if path not in OPEN_PATHS and not self.token_ok(h.get("authorization", "")):
            return Verdict(401, "unauthorized", cors)
        return Verdict(None, "", cors)


def build_gate(bind_host: str, port: int, env=None) -> Gate:
    """按监听地址和环境变量建关口；配置不安全时抛 StartupError。"""
    env = os.environ if env is None else env
    lan = env.get("BRIDGE_LAN", "") == "1"
    token = env.get("BRIDGE_TOKEN", "")
    if bind_host not in LOOPBACK and not lan:
        raise StartupError("监听 %s 不是本机地址：要对外监听必须设 BRIDGE_LAN=1 和 BRIDGE_TOKEN" % bind_host)
    if lan and not token:
        raise StartupError("BRIDGE_LAN=1 时必须设 BRIDGE_TOKEN，令牌为空拒绝启动")
    hosts = {"%s:%s" % (_host_key(name), port) for name in LOOPBACK}
    hosts.update(_host_key(item) for item in _split(env.get("BRIDGE_ALLOWED_HOSTS", "")))
    origins = frozenset(_split(env.get("BRIDGE_CORS_ORIGINS", "")))
    return Gate(token=token, allowed_hosts=frozenset(hosts), cors_origins=origins)


def asgi_guard(app, gate: Gate):
    """给 ASGI 应用（MCP streamable-http）套上同一个关口。"""

    async def guarded(scope, receive, send):
        if scope.get("type") != "http":
            await app(scope, receive, send)
            return
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
        verdict = gate.evaluate(scope.get("method", "GET"), scope.get("path", ""), headers)
        extra = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in verdict.headers]
        if verdict.status is not None:
            body = b"" if verdict.status == 204 else json.dumps({"error": verdict.error}).encode("utf-8")
            start = [(b"content-length", str(len(body)).encode("ascii"))] + extra
            if body:
                start.append((b"content-type", b"application/json"))
            await send({"type": "http.response.start", "status": verdict.status, "headers": start})
            await send({"type": "http.response.body", "body": body})
            return

        async def send_with_cors(message):
            if message.get("type") == "http.response.start" and extra:
                message = dict(message, headers=list(message.get("headers", [])) + extra)
            await send(message)

        await app(scope, receive, send_with_cors)

    return guarded


def check_navigation_url(url: str) -> str:
    """导航只允许 http、https 和 about:blank，挡住 file:// 之类读本机文件的地址。"""
    value = (url or "").strip()
    if value == "about:blank":
        return value
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ValueError("只允许 http、https 或 about:blank 地址：%s" % value[:200])
    return value
