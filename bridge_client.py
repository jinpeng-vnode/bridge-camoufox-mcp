"""
Python client for a running Bridge Camoufox MCP server.

1. BridgeClient — async wrappers around MCP tools
2. PageAdapter — small sync Playwright-like subset

    from bridge_client import BridgeClient, PageAdapter

    client = BridgeClient()
    await client.connect()
    await client.goto("https://example.com")

    page = PageAdapter(client)
    page.goto("https://example.com")
    page.locator("button").click()
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

log = logging.getLogger("bridge_client")

DEFAULT_SERVER_URL = "http://127.0.0.1:3180/mcp"


class BridgeClient:
    """Bridge MCP 异步客户端"""

    def __init__(self, server_url: str = DEFAULT_SERVER_URL):
        self.server_url = server_url
        self._session = None
        self._transport_cm = None
        self._session_cm = None

    async def connect(self):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        self._transport_cm = streamablehttp_client(self.server_url)
        read, write, _ = await self._transport_cm.__aenter__()
        self._session_cm = ClientSession(read, write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        log.info(f"已连接到 Bridge MCP: {self.server_url}")

    async def close(self):
        try:
            if self._session_cm:
                await self._session_cm.__aexit__(None, None, None)
        except Exception:
            pass
        try:
            if self._transport_cm:
                await self._transport_cm.__aexit__(None, None, None)
        except Exception:
            pass  # anyio task scope 在 sync 桥接时可能报错，忽略即可
        self._session = None

    async def call_tool(self, name: str, arguments: dict = None) -> str:
        """调用 MCP 工具，返回文本结果"""
        if not self._session:
            raise RuntimeError("未连接，请先调用 connect()")
        result = await self._session.call_tool(name, arguments or {})
        return result.content[0].text if result.content else ""

    # ── 便捷方法 ──

    async def goto(self, url: str, **kw) -> str:
        args = {"url": url}
        if "wait_until" in kw:
            args["wait_until"] = kw["wait_until"]
        if "timeout" in kw:
            args["timeout"] = kw["timeout"]
        return await self.call_tool("goto", args)

    async def click(self, selector: str, timeout: int = 5000) -> str:
        return await self.call_tool("click", {"selector": selector, "timeout": timeout})

    async def fill(self, selector: str, value: str) -> str:
        return await self.call_tool("fill", {"selector": selector, "value": value})

    async def has_text(self, text: str, timeout: int = 2000) -> bool:
        r = await self.call_tool("has_text", {"text": text, "timeout": timeout})
        return r.lower() == "true"

    async def get_url(self) -> str:
        return await self.call_tool("get_url")

    async def screenshot(self, path: str = "") -> str:
        return await self.call_tool("screenshot", {"path": path})


# ═══════════════════════════════════════════════
#  PageAdapter — Playwright Page 兼容层（sync）
# ═══════════════════════════════════════════════

class PageAdapter:
    """
    模拟 Playwright Page API，底层通过 BridgeClient 调用 MCP。
    让现有状态机代码无需大改。
    """

    def __init__(self, client: BridgeClient, loop: asyncio.AbstractEventLoop | None = None):
        self._client = client
        self._loop = loop or asyncio.get_event_loop()

    def _sync(self, coro):
        """async → sync 桥接"""
        return self._loop.run_until_complete(coro)

    @property
    def url(self) -> str:
        return self._sync(self._client.get_url())

    def goto(self, url: str, **kwargs):
        self._sync(self._client.goto(url, **kwargs))

    def go_back(self, **kwargs):
        timeout = kwargs.get("timeout", 30000)
        self._sync(self._client.call_tool("go_back", {"timeout": timeout}))

    def title(self) -> str:
        return self._sync(self._client.call_tool("get_page_title"))

    def evaluate(self, expression: str) -> Any:
        result = self._sync(self._client.call_tool("evaluate", {"expression": expression}))
        try:
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return result

    def screenshot(self, **kwargs):
        path = kwargs.get("path", "")
        full_page = kwargs.get("full_page", False)
        return self._sync(self._client.call_tool("screenshot", {
            "path": path, "full_page": full_page
        }))

    def locator(self, selector: str) -> "LocatorAdapter":
        return LocatorAdapter(self._client, self._loop, selector)

    def frame_locator(self, selector: str) -> "FrameLocatorAdapter":
        return FrameLocatorAdapter(self._client, self._loop, selector)


class LocatorAdapter:
    """模拟 Playwright Locator"""

    def __init__(self, client: BridgeClient, loop, selector: str):
        self._client = client
        self._loop = loop
        self._selector = selector

    def _sync(self, coro):
        return self._loop.run_until_complete(coro)

    def click(self, **kwargs):
        timeout = kwargs.get("timeout", 5000)
        self._sync(self._client.click(self._selector, timeout))

    def fill(self, value: str, **kwargs):
        self._sync(self._client.fill(self._selector, value))

    def inner_text(self) -> str:
        r = self._sync(self._client.call_tool("find_element", {"selector": self._selector}))
        # find_element 返回 "found | tag=X | text=Y"
        if "text=" in r:
            return r.split("text=", 1)[1]
        return ""

    def get_attribute(self, name: str) -> str | None:
        r = self._sync(self._client.call_tool("get_attribute", {
            "selector": self._selector, "attr_name": name
        }))
        return r if r else None

    def wait_for(self, state: str = "attached", timeout: int = 30000):
        """等待元素出现"""
        r = self._sync(self._client.call_tool("find_element", {
            "selector": self._selector, "timeout": timeout
        }))
        if "not_found" in r and state != "detached":
            raise TimeoutError(f"等待元素超时: {self._selector}")

    def select_option(self, value: str):
        self._sync(self._client.call_tool("select_option", {
            "selector": self._selector, "value": value
        }))

    def count(self) -> int:
        r = self._sync(self._client.call_tool("find_elements", {"selector": self._selector}))
        # "count=N"
        try:
            return int(r.split("=")[1])
        except (IndexError, ValueError):
            return 0

    @property
    def first(self):
        return self  # find_element 默认操作第一个

    def all(self):
        n = self.count()
        return [LocatorAdapter(self._client, self._loop,
                               f"{self._selector} >> nth={i}") for i in range(n)]


class FrameLocatorAdapter:
    """模拟 Playwright FrameLocator"""

    def __init__(self, client: BridgeClient, loop, frame_selector: str):
        self._client = client
        self._loop = loop
        self._frame_selector = frame_selector

    def _sync(self, coro):
        return self._loop.run_until_complete(coro)

    def locator(self, selector: str) -> "FrameElementAdapter":
        return FrameElementAdapter(self._client, self._loop, self._frame_selector, selector)


class FrameElementAdapter:
    """模拟 iframe 内的 Locator"""

    def __init__(self, client: BridgeClient, loop, frame_selector: str, element_selector: str):
        self._client = client
        self._loop = loop
        self._frame = frame_selector
        self._element = element_selector

    def _sync(self, coro):
        return self._loop.run_until_complete(coro)

    def click(self, **kwargs):
        timeout = kwargs.get("timeout", 5000)
        self._sync(self._client.call_tool("frame_click", {
            "frame_selector": self._frame,
            "element_selector": self._element,
            "timeout": timeout,
        }))

    def wait_for(self, state: str = "attached", timeout: int = 5000):
        r = self._sync(self._client.call_tool("frame_find", {
            "frame_selector": self._frame,
            "element_selector": self._element,
            "timeout": timeout,
        }))
        if "not_found" in r and state != "detached":
            raise TimeoutError(f"等待 iframe 元素超时: {self._frame} >> {self._element}")

    @property
    def first(self):
        return self
