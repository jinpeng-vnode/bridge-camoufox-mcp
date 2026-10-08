"""
Bridge Camoufox MCP — share one Camoufox browser across MCP clients and scripts.

Transport: Streamable HTTP (default http://127.0.0.1:3180/mcp)

    python main.py
    BRIDGE_HOST=127.0.0.1 BRIDGE_PORT=3180 python main.py
"""
from __future__ import annotations

import glob
import inspect
import logging
import os
import shutil
import time
import uuid

from camoufox.async_api import AsyncCamoufox
from mcp.server.fastmcp import FastMCP
from playwright.async_api import Page

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

_browser_cm = None
_browser = None
_page: Page | None = None
_cache_dir: str | None = None

_CACHE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_cache")


def _create_isolated_cache() -> str:
    """创建独立缓存目录（数据隔离），清理超过 1 小时的旧缓存"""
    os.makedirs(_CACHE_ROOT, exist_ok=True)
    # 清理旧缓存
    for old in glob.glob(os.path.join(_CACHE_ROOT, "cache_*")):
        if os.path.isdir(old):
            age = time.time() - os.path.getmtime(old)
            if age > 3600:
                try:
                    shutil.rmtree(old)
                    log.info(f"已清理过期缓存: {os.path.basename(old)}")
                except Exception as e:
                    log.warning(f"清理缓存失败: {os.path.basename(old)} - {e}")
    # 创建新缓存
    cache_id = uuid.uuid4().hex[:8]
    cache_path = os.path.join(_CACHE_ROOT, f"cache_{cache_id}")
    os.makedirs(cache_path, exist_ok=True)
    log.info(f"✓ 已创建独立缓存目录: {cache_path}")
    return cache_path


async def _get_page() -> Page:
    """获取当前 page，未启动则报错"""
    if _page is None:
        raise RuntimeError("浏览器未启动，请先调用 launch_browser")
    return _page


# ═══════════════════════════════════════════
#  浏览器管理
# ═══════════════════════════════════════════

@mcp.tool()
async def launch_browser(
    proxy_server: str = "",
    humanize: bool = True,
    geoip: bool = False,
    locale: str = "",
) -> str:
    """启动 Camoufox 浏览器（幂等，已启动则返回状态）"""
    global _browser_cm, _browser, _page, _cache_dir
    if _page is not None:
        return f"浏览器已在运行，当前 URL: {_page.url}"

    kwargs = {
        # ── 固定参数（与直连 Camoufox 版完全一致）──
        "headless": False,              # 必须可视化，禁止无头
        "humanize": humanize,
        "geoip": geoip,
        "block_webrtc": True,           # 屏蔽 WebRTC，防止真实 IP 泄漏
        "firefox_user_prefs": {
            # DNS over HTTPS (DoH) 防泄漏
            'network.trr.mode': 3,                              # 强制 DoH
            'network.trr.uri': 'https://dns.google/dns-query',  # Google DoH
            # 禁用 DNS 预取，防止 DNS 泄漏
            'network.dns.disablePrefetch': True,
            'network.prefetch-next': False,
        },
    }
    if proxy_server:
        kwargs["proxy"] = {"server": proxy_server}
    if locale:
        kwargs["locale"] = locale

    # 数据隔离：每次启动使用独立缓存目录
    _cache_dir = _create_isolated_cache()
    kwargs["persistent_context"] = True
    kwargs["user_data_dir"] = _cache_dir

    _browser_cm = AsyncCamoufox(**kwargs)
    _browser = await _browser_cm.__aenter__()

    # Camoufox 返回 BrowserContext 或 Browser
    if hasattr(_browser, "contexts"):
        ctx = _browser.contexts[0] if _browser.contexts else await _browser.new_context()
    else:
        ctx = _browser

    pages = ctx.pages
    _page = pages[0] if pages else await ctx.new_page()
    log.info(f"浏览器启动成功，page URL: {_page.url}")
    return "浏览器启动成功"


@mcp.tool()
async def close_browser() -> str:
    """关闭浏览器并清理缓存目录"""
    global _browser_cm, _browser, _page, _cache_dir
    if _browser_cm:
        await _browser_cm.__aexit__(None, None, None)
    # 清理本次缓存目录
    if _cache_dir and os.path.isdir(_cache_dir):
        try:
            shutil.rmtree(_cache_dir)
            log.info(f"✓ 已清理缓存目录: {_cache_dir}")
        except Exception as e:
            log.warning(f"清理缓存目录失败: {e}")
    _browser_cm = _browser = _page = _cache_dir = None
    log.info("浏览器已关闭")
    return "浏览器已关闭"


@mcp.tool()
async def browser_status() -> str:
    """获取浏览器状态"""
    if _page is None:
        return "浏览器未启动"
    try:
        url = _page.url
        title = await _page.title()
        return f"运行中 | URL: {url} | Title: {title}"
    except Exception as e:
        return f"浏览器异常: {e}"


# ═══════════════════════════════════════════
#  导航
# ═══════════════════════════════════════════

@mcp.tool()
async def goto(url: str, wait_until: str = "load", timeout: int = 30000) -> str:
    """导航到指定 URL"""
    page = await _get_page()
    await page.goto(url, wait_until=wait_until, timeout=timeout)
    return f"已导航到: {page.url}"


@mcp.tool()
async def go_back(timeout: int = 30000) -> str:
    """浏览器后退"""
    page = await _get_page()
    await page.go_back(timeout=timeout)
    return f"已后退到: {page.url}"


@mcp.tool()
async def get_url() -> str:
    """获取当前页面 URL"""
    page = await _get_page()
    return page.url


@mcp.tool()
async def get_page_title() -> str:
    """获取页面标题"""
    page = await _get_page()
    return await page.title()


# ═══════════════════════════════════════════
#  交互
# ═══════════════════════════════════════════

@mcp.tool()
async def click(selector: str, timeout: int = 5000) -> str:
    """点击元素"""
    page = await _get_page()
    await page.locator(selector).click(timeout=timeout)
    return f"已点击: {selector}"


@mcp.tool()
async def fill(selector: str, value: str, timeout: int = 5000) -> str:
    """填充输入框"""
    page = await _get_page()
    await page.locator(selector).fill(value, timeout=timeout)
    return f"已填充: {selector}"


@mcp.tool()
async def select_option(selector: str, value: str) -> str:
    """下拉框选择"""
    page = await _get_page()
    await page.locator(selector).select_option(value)
    return f"已选择: {selector} = {value}"


@mcp.tool()
async def press_key(key: str) -> str:
    """按键"""
    page = await _get_page()
    await page.keyboard.press(key)
    return f"已按键: {key}"


# ═══════════════════════════════════════════
#  查询
# ═══════════════════════════════════════════

@mcp.tool()
async def find_element(selector: str, timeout: int = 2000) -> str:
    """查找元素，返回是否存在及属性"""
    page = await _get_page()
    try:
        loc = page.locator(selector)
        await loc.first.wait_for(state="attached", timeout=timeout)
        tag = await loc.first.evaluate("el => el.tagName")
        text = (await loc.first.inner_text())[:100]
        return f"found | tag={tag} | text={text}"
    except Exception:
        return "not_found"


@mcp.tool()
async def find_elements(selector: str) -> str:
    """查找所有匹配元素，返回数量"""
    page = await _get_page()
    count = await page.locator(selector).count()
    return f"count={count}"


@mcp.tool()
async def has_text(text: str, timeout: int = 2000) -> str:
    """检查页面是否包含指定文本"""
    page = await _get_page()
    try:
        loc = page.locator(f"text={text}")
        await loc.first.wait_for(state="attached", timeout=timeout)
        return "true"
    except Exception:
        return "false"


@mcp.tool()
async def get_attribute(selector: str, attr_name: str) -> str:
    """获取元素属性"""
    page = await _get_page()
    val = await page.locator(selector).first.get_attribute(attr_name)
    return val or ""


@mcp.tool()
async def evaluate(expression: str) -> str:
    """执行 JavaScript 表达式"""
    page = await _get_page()
    result = await page.evaluate(expression)
    return str(result)


# ═══════════════════════════════════════════
#  截图
# ═══════════════════════════════════════════

@mcp.tool()
async def screenshot(path: str = "", full_page: bool = False) -> str:
    """页面截图"""
    page = await _get_page()
    kwargs = {"full_page": full_page}
    if path:
        kwargs["path"] = path
    data = await page.screenshot(**kwargs)
    if path:
        return f"截图已保存: {path}"
    return f"截图完成 ({len(data)} bytes)"


# ═══════════════════════════════════════════
#  iframe 操作
# ═══════════════════════════════════════════

@mcp.tool()
async def frame_click(frame_selector: str, element_selector: str, timeout: int = 5000) -> str:
    """在 iframe 内点击元素"""
    page = await _get_page()
    frame = page.frame_locator(frame_selector)
    await frame.locator(element_selector).click(timeout=timeout)
    return f"已在 iframe({frame_selector}) 内点击: {element_selector}"


@mcp.tool()
async def frame_find(frame_selector: str, element_selector: str, timeout: int = 2000) -> str:
    """在 iframe 内查找元素"""
    page = await _get_page()
    try:
        frame = page.frame_locator(frame_selector)
        await frame.locator(element_selector).first.wait_for(state="attached", timeout=timeout)
        return "found"
    except Exception:
        return "not_found"


def main() -> None:
    log.info("listening at http://%s:%s/mcp (streamable-http)", HOST, PORT)
    kwargs: dict = {"transport": "streamable-http"}
    params = inspect.signature(mcp.run).parameters
    if "host" in params:
        kwargs["host"] = HOST
    if "port" in params:
        kwargs["port"] = PORT
    mcp.run(**kwargs)


if __name__ == "__main__":
    main()
