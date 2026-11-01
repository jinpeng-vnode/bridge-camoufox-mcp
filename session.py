"""单个 Camoufox 会话。同一时间只开一个窗口，账号配置目录可复用。"""

from __future__ import annotations

import asyncio
import logging
import os

from camoufox.async_api import AsyncCamoufox
from playwright.async_api import Page

from profile_util import profile_dir, remove_if_ephemeral, screenshot_path
from security import check_navigation_url

log = logging.getLogger("bridge")

FIREFOX_PREFS = {
    "network.trr.mode": 3,
    "network.trr.uri": "https://dns.google/dns-query",
    "network.dns.disablePrefetch": True,
    "network.prefetch-next": False,
            "browser.cache.disk.enable": False,
            "browser.cache.disk.capacity": 0,
            "browser.cache.offline.enable": False,
            "security.sandbox.content.level": 0,
}


class SessionManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._browser_cm = None
        self._browser = None
        self._page: Page | None = None
        self._cache_dir: str | None = None
        self._account_id = ""

    def snapshot(self) -> dict:
        return {
            "running": self._page is not None,
            "account_id": self._account_id,
            "user_data_dir": self._cache_dir or "",
            "url": getattr(self._page, "url", ""),
        }

    async def _get_page(self) -> Page:
        if self._page is None:
            raise RuntimeError("浏览器未启动，请先打开会话")
        return self._page

    async def launch(
        self,
        proxy_server: str = "",
        humanize: bool = True,
        geoip: bool = False,
        locale: str = "",
        account_id: str = "",
        user_data_dir: str = "",
    ) -> dict:
        async with self._lock:
            if self._page is not None:
                same = account_id and self._account_id == account_id
                if same or (not account_id and not user_data_dir):
                    return {"ok": True, "reused": True, **self.snapshot()}
            # 先校验路径再关旧会话：路径不合法时不打断正在用的浏览器
            cache = profile_dir(account_id, user_data_dir)
            if self._page is not None:
                await self._close_locked()
            kwargs = {
                "headless": False,
                "humanize": humanize,
                "geoip": geoip or bool(proxy_server),
                "block_webrtc": True,
                "window": (1280, 800),
                "firefox_user_prefs": dict(FIREFOX_PREFS),
                "persistent_context": True,
                "user_data_dir": cache,
            }
            if os.environ.get("DISPLAY"):
                # 容器里画到 Xvfb，供 noVNC 观看；不要用 Firefox 无头模式
                kwargs["headless"] = False
            if proxy_server:
                kwargs["proxy"] = {"server": proxy_server}
            if locale:
                kwargs["locale"] = locale

            self._browser_cm = AsyncCamoufox(**kwargs)
            self._browser = await self._browser_cm.__aenter__()
            if hasattr(self._browser, "contexts"):
                ctx = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
            else:
                ctx = self._browser
            pages = ctx.pages
            self._page = pages[0] if pages else await ctx.new_page()
            self._cache_dir = cache
            self._account_id = account_id
            log.info("浏览器启动成功 account=%s dir=%s url=%s", account_id, cache, self._page.url)
            return {"ok": True, "reused": False, **self.snapshot()}

    async def close(self) -> dict:
        async with self._lock:
            return await self._close_locked()

    async def _close_locked(self) -> dict:
        account_id = self._account_id
        cache = self._cache_dir
        if self._browser_cm:
            await self._browser_cm.__aexit__(None, None, None)
        remove_if_ephemeral(cache or "")
        self._browser_cm = self._browser = self._page = self._cache_dir = None
        self._account_id = ""
        log.info("浏览器已关闭 account=%s", account_id)
        return {"ok": True, "account_id": account_id, "user_data_dir": cache or ""}

    async def status(self) -> dict:
        if self._page is None:
            return {"running": False}
        try:
            title = await self._page.title()
            return {"ok": True, "title": title, **self.snapshot()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), **self.snapshot()}

    async def goto(self, url: str, wait_until: str = "load", timeout: int = 30000) -> dict:
        url = check_navigation_url(url)
        page = await self._get_page()
        await page.goto(url, wait_until=wait_until, timeout=timeout)
        return {"ok": True, "url": page.url}

    async def go_back(self, timeout: int = 30000) -> dict:
        page = await self._get_page()
        await page.go_back(timeout=timeout)
        return {"ok": True, "url": page.url}

    async def get_url(self) -> dict:
        page = await self._get_page()
        return {"ok": True, "url": page.url}

    async def get_page_title(self) -> dict:
        page = await self._get_page()
        return {"ok": True, "title": await page.title()}

    async def click(self, selector: str, timeout: int = 5000) -> dict:
        page = await self._get_page()
        await page.locator(selector).click(timeout=timeout)
        return {"ok": True, "selector": selector}

    async def fill(self, selector: str, value: str, timeout: int = 5000) -> dict:
        page = await self._get_page()
        await page.locator(selector).fill(value, timeout=timeout)
        return {"ok": True, "selector": selector}

    async def select_option(self, selector: str, value: str) -> dict:
        page = await self._get_page()
        await page.locator(selector).select_option(value)
        return {"ok": True, "selector": selector, "value": value}

    async def press_key(self, key: str) -> dict:
        page = await self._get_page()
        await page.keyboard.press(key)
        return {"ok": True, "key": key}

    async def find_element(self, selector: str, timeout: int = 2000) -> dict:
        page = await self._get_page()
        try:
            loc = page.locator(selector)
            await loc.first.wait_for(state="attached", timeout=timeout)
            tag = await loc.first.evaluate("el => el.tagName")
            text = (await loc.first.inner_text())[:100]
            return {"ok": True, "found": True, "tag": tag, "text": text}
        except Exception:
            return {"ok": True, "found": False}

    async def find_elements(self, selector: str) -> dict:
        page = await self._get_page()
        return {"ok": True, "count": await page.locator(selector).count()}

    async def has_text(self, text: str, timeout: int = 2000) -> dict:
        page = await self._get_page()
        try:
            loc = page.locator("text=%s" % text)
            await loc.first.wait_for(state="attached", timeout=timeout)
            return {"ok": True, "found": True}
        except Exception:
            return {"ok": True, "found": False}

    async def get_attribute(self, selector: str, attr_name: str) -> dict:
        page = await self._get_page()
        val = await page.locator(selector).first.get_attribute(attr_name)
        return {"ok": True, "value": val or ""}

    async def evaluate(self, expression: str) -> dict:
        page = await self._get_page()
        return {"ok": True, "result": await page.evaluate(expression)}

    async def screenshot(self, path: str = "", full_page: bool = False) -> dict:
        page = await self._get_page()
        kwargs = {"full_page": full_page}
        if path:
            path = screenshot_path(path)
            kwargs["path"] = path
        data = await page.screenshot(**kwargs)
        return {"ok": True, "bytes": len(data), "path": path}

    async def frame_click(self, frame_selector: str, element_selector: str, timeout: int = 5000) -> dict:
        page = await self._get_page()
        frame = page.frame_locator(frame_selector)
        await frame.locator(element_selector).click(timeout=timeout)
        return {"ok": True}

    async def frame_find(self, frame_selector: str, element_selector: str, timeout: int = 2000) -> dict:
        page = await self._get_page()
        try:
            frame = page.frame_locator(frame_selector)
            await frame.locator(element_selector).first.wait_for(state="attached", timeout=timeout)
            return {"ok": True, "found": True}
        except Exception:
            return {"ok": True, "found": False}
