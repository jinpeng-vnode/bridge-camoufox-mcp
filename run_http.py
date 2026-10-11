"""只启动给账号池用的 HTTP，不依赖 MCP 包。"""

import asyncio
import logging
import os
import threading

from http_api import start_http_server
from session import SessionManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [Bridge] %(message)s")
log = logging.getLogger("bridge")

manager = SessionManager()
browser_loop = asyncio.new_event_loop()


def _browser_thread():
    asyncio.set_event_loop(browser_loop)
    browser_loop.run_forever()


def call_manager(name, arguments=None, timeout=90):
    method = getattr(manager, name)
    future = asyncio.run_coroutine_threadsafe(method(**(arguments or {})), browser_loop)
    return future.result(timeout=timeout)


if __name__ == "__main__":
    host = os.environ.get("BRIDGE_HTTP_HOST", "127.0.0.1")
    port = int(os.environ.get("BRIDGE_HTTP_PORT", "3181"))
    token = os.environ.get("BRIDGE_TOKEN", "")
    threading.Thread(target=_browser_thread, daemon=True).start()
    log.info("浏览器 HTTP 启动 %s:%s", host, port)
    start_http_server(host, port, call_manager, token)
