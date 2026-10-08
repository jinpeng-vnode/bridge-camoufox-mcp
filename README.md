# bridge-camoufox-mcp

Share **one** [Camoufox](https://camoufox.com/) (anti-detect Firefox) instance across multiple MCP clients and Python scripts.

Stdio MCP servers spawn a browser per client. This server speaks **Streamable HTTP**, so Cursor, Claude, and your own scripts can all drive the same visible browser.

中文说明见下方。

## Requirements

- Python 3.10+
- A machine that can run Camoufox / Firefox (not headless — the window stays visible on purpose)

## Install

```bash
git clone https://github.com/jinpeng-vnode/bridge-camoufox-mcp.git
cd bridge-camoufox-mcp
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e .
python -m camoufox fetch
```

`geoip=True` on `launch_browser` also needs:

```bash
pip install -e ".[geoip]"
```

## Run

```bash
python main.py
# or: bridge-camoufox-mcp
```

Listens on `http://127.0.0.1:3180/mcp` by default.

| Env | Default | Meaning |
| --- | --- | --- |
| `BRIDGE_HOST` | `127.0.0.1` | Bind address. Keep loopback unless you add your own auth. |
| `BRIDGE_PORT` | `3180` | HTTP port |

## Connect an MCP client

Start the server first, then point the client at the URL.

Cursor / Claude-compatible `mcp.json`:

```json
{
  "mcpServers": {
    "bridge-camoufox": {
      "url": "http://127.0.0.1:3180/mcp"
    }
  }
}
```

## Python client

```python
import asyncio
from bridge_client import BridgeClient, PageAdapter

async def main():
    client = BridgeClient("http://127.0.0.1:3180/mcp")
    await client.connect()
    try:
        await client.call_tool("launch_browser", {"humanize": True})
        await client.goto("https://example.com")
        print(await client.get_url())
    finally:
        await client.call_tool("close_browser")
        await client.close()

asyncio.run(main())
```

`PageAdapter` is a small sync subset of Playwright (`goto`, `locator().click()`, frames). It is not a full Playwright drop-in.

## Tools

| Tool | Role |
| --- | --- |
| `launch_browser` | Start Camoufox (idempotent). Optional `proxy_server`, `humanize`, `geoip`, `locale`. |
| `close_browser` | Quit and delete this session's profile dir |
| `browser_status` | URL + title |
| `goto` / `go_back` / `get_url` / `get_page_title` | Navigation |
| `click` / `fill` / `select_option` / `press_key` | Input |
| `find_element` / `find_elements` / `has_text` / `get_attribute` | Query |
| `evaluate` | Run JavaScript in the page |
| `screenshot` | PNG to a path or size-only |
| `frame_click` / `frame_find` | iframe locators |

Each `launch_browser` uses a fresh `browser_cache/cache_*` directory and deletes caches older than one hour.

## Security

- No authentication. Default bind is loopback only.
- Do not expose `BRIDGE_HOST=0.0.0.0` to a network you do not trust.
- `evaluate` runs arbitrary JS **in the live page**. Treat it like a debugger.
- WebRTC is blocked; Firefox is forced onto DNS-over-HTTPS. That reduces IP leaks, it is not a VPN.

## License

MIT. See [LICENSE](LICENSE).

---

## 中文

这是一个 **Streamable HTTP** MCP 服务：多个 MCP 客户端和 Python 脚本共用同一个 Camoufox 窗口，而不是每连一次就再开一个浏览器。

```bash
pip install -e .
python -m camoufox fetch
python main.py
```

默认只监听 `127.0.0.1:3180`，没有鉴权。客户端填：

```json
{ "mcpServers": { "bridge-camoufox": { "url": "http://127.0.0.1:3180/mcp" } } }
```
