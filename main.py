"""
Bridge Camoufox MCP — share one Camoufox browser across MCP clients and scripts.

MCP（streamable-http，默认 3180）给脚本用。
普通 HTTP（默认 3181）给账号池按账号开关浏览器。

    python main.py
    BRIDGE_HOST=127.0.0.1 BRIDGE_PORT=3180 python main.py
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import threading

from mcp.server.fastmcp import FastMCP

from http_api import start_http_server
from session import SessionManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [bridge-camoufox-mcp] %(message)s")
log = logging.getLogger("bridge-camoufox-mcp")

HOST = os.environ.get("BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("BRIDGE_PORT", "3180"))

mcp = FastMCP("bridge-camoufox-mcp")
_settings = getattr(mcp, "settings", None)
if _settings is not None:
    if hasattr(_settings, "host"):
        _settings.host = HOST
    if hasattr(_settings, "port"):
        _settings.port = PORT

manager = SessionManager()
_browser_loop = asyncio.new_event_loop()


def _browser_thread():
    asyncio.set_event_loop(_browser_loop)
    _browser_loop.run_forever()


def call_manager(name: str, arguments: dict | None = None, timeout: float = 90):
    method = getattr(manager, name)
    future = asyncio.run_coroutine_threadsafe(method(**(arguments or {})), _browser_loop)
    return future.result(timeout=timeout)


async def _tool(name: str, arguments: dict | None = None, timeout: float = 90):
    future = asyncio.run_coroutine_threadsafe(getattr(manager, name)(**(arguments or {})), _browser_loop)
    return await asyncio.wrap_future(future)


@mcp.tool()
async def launch_browser(
    proxy_server: str = "",
    humanize: bool = True,
    geoip: bool = False,
    locale: str = "",
    account_id: str = "",
    user_data_dir: str = "",
) -> str:
    """启动 Camoufox。带 account_id / user_data_dir 时保留配置目录。"""
    result = await _tool(
        "launch",
        {
            "proxy_server": proxy_server,
            "humanize": humanize,
            "geoip": geoip,
            "locale": locale,
            "account_id": account_id,
            "user_data_dir": user_data_dir,
        },
        timeout=90,
    )
    if result.get("reused"):
        return "浏览器已在运行，当前 URL: %s" % result.get("url", "")
    return "浏览器启动成功"


@mcp.tool()
async def close_browser() -> str:
    """关闭浏览器。临时缓存会删，账号配置目录会留下。"""
    await _tool("close", {}, timeout=30)
    return "浏览器已关闭"


@mcp.tool()
async def browser_status() -> str:
    """获取浏览器状态"""
    result = await _tool("status", {}, timeout=15)
    if not result.get("running"):
        return "浏览器未启动"
    if result.get("error"):
        return "浏览器异常: %s" % result["error"]
    return "运行中 | URL: %s | Title: %s" % (result.get("url"), result.get("title"))


@mcp.tool()
async def goto(url: str, wait_until: str = "load", timeout: int = 30000) -> str:
    """导航到指定 URL"""
    result = await _tool("goto", {"url": url, "wait_until": wait_until, "timeout": timeout})
    return "已导航到: %s" % result.get("url")


@mcp.tool()
async def go_back(timeout: int = 30000) -> str:
    """浏览器后退"""
    result = await _tool("go_back", {"timeout": timeout})
    return "已后退到: %s" % result.get("url")


@mcp.tool()
async def get_url() -> str:
    """获取当前页面 URL"""
    return str((await _tool("get_url")).get("url") or "")


@mcp.tool()
async def get_page_title() -> str:
    """获取页面标题"""
    return str((await _tool("get_page_title")).get("title") or "")


@mcp.tool()
async def click(selector: str, timeout: int = 5000) -> str:
    """点击元素"""
    await _tool("click", {"selector": selector, "timeout": timeout})
    return "已点击: %s" % selector


@mcp.tool()
async def fill(selector: str, value: str, timeout: int = 5000) -> str:
    """填充输入框"""
    await _tool("fill", {"selector": selector, "value": value, "timeout": timeout})
    return "已填充: %s" % selector


@mcp.tool()
async def select_option(selector: str, value: str) -> str:
    """下拉框选择"""
    await _tool("select_option", {"selector": selector, "value": value})
    return "已选择: %s = %s" % (selector, value)


@mcp.tool()
async def press_key(key: str) -> str:
    """按键"""
    await _tool("press_key", {"key": key})
    return "已按键: %s" % key


@mcp.tool()
async def find_element(selector: str, timeout: int = 2000) -> str:
    """查找元素，返回是否存在及属性"""
    result = await _tool("find_element", {"selector": selector, "timeout": timeout})
    if not result.get("found"):
        return "not_found"
    return "found | tag=%s | text=%s" % (result.get("tag"), result.get("text"))


@mcp.tool()
async def find_elements(selector: str) -> str:
    """查找所有匹配元素，返回数量"""
    result = await _tool("find_elements", {"selector": selector})
    return "count=%s" % result.get("count")


@mcp.tool()
async def has_text(text: str, timeout: int = 2000) -> str:
    """检查页面是否包含指定文本"""
    result = await _tool("has_text", {"text": text, "timeout": timeout})
    return "true" if result.get("found") else "false"


@mcp.tool()
async def get_attribute(selector: str, attr_name: str) -> str:
    """获取元素属性"""
    return str((await _tool("get_attribute", {"selector": selector, "attr_name": attr_name})).get("value") or "")


@mcp.tool()
async def evaluate(expression: str) -> str:
    """执行 JavaScript 表达式"""
    return str((await _tool("evaluate", {"expression": expression})).get("result"))


@mcp.tool()
async def screenshot(path: str = "", full_page: bool = False) -> str:
    """页面截图"""
    result = await _tool("screenshot", {"path": path, "full_page": full_page})
    if path:
        return "截图已保存: %s" % path
    return "截图完成 (%s bytes)" % result.get("bytes")


@mcp.tool()
async def frame_click(frame_selector: str, element_selector: str, timeout: int = 5000) -> str:
    """在 iframe 内点击元素"""
    await _tool(
        "frame_click",
        {"frame_selector": frame_selector, "element_selector": element_selector, "timeout": timeout},
    )
    return "已在 iframe(%s) 内点击: %s" % (frame_selector, element_selector)


@mcp.tool()
async def frame_find(frame_selector: str, element_selector: str, timeout: int = 2000) -> str:
    """在 iframe 内查找元素"""
    result = await _tool(
        "frame_find",
        {"frame_selector": frame_selector, "element_selector": element_selector, "timeout": timeout},
    )
    return "found" if result.get("found") else "not_found"


def main() -> None:
    threading.Thread(target=_browser_thread, daemon=True).start()
    http_host = os.environ.get("BRIDGE_HTTP_HOST", "0.0.0.0")
    http_port = int(os.environ.get("BRIDGE_HTTP_PORT", "3181"))
    token = os.environ.get("BRIDGE_TOKEN", "")
    threading.Thread(
        target=start_http_server,
        args=(http_host, http_port, call_manager, token),
        daemon=True,
    ).start()
    log.info("listening at http://%s:%s/mcp ; http://%s:%s", HOST, PORT, http_host, http_port)
    kwargs: dict = {"transport": "streamable-http"}
    params = inspect.signature(mcp.run).parameters
    if "host" in params:
        kwargs["host"] = HOST
    if "port" in params:
        kwargs["port"] = PORT
    mcp.run(**kwargs)


if __name__ == "__main__":
    main()
