"""Web Scout MCP Server v0.2 — Entry point with 19 tools."""

import os

from fastmcp import FastMCP

from web_scout import state
from web_scout.browser import BrowserSession
from web_scout.monitor import NetworkMonitor
from web_scout.dom import DOMScanner
from web_scout.login import LoginDetector
from web_scout.export import Exporter

# Clear previous response directory on startup
_response_dir = os.environ.get("RESPONSE_DIR", "./response")
if os.path.exists(_response_dir):
    import shutil
    shutil.rmtree(_response_dir)

# Create MCP instance
mcp = FastMCP("web-scout", instructions="""
Web Scout discovers web API endpoints and DOM data structures for AI agents to write
scrapers. Uses a real browser to render JS, capture XHR/Fetch requests, scan DOM,
and output compressed field docs. NOT a scraper — does not forge requests, reverse
wasm, or bypass encryption.

RECOMMENDED WORKFLOW:

  Fast path (recommended):
    scout_open(url) -> pick a keyword from text
    scout_act("scroll") -> trigger feed/recommendation APIs
    scout_search(keyword) -> find which API contains it
    scout_context(keyword) -> see field path and value
    scout_inspect(n) -> request params + response structure
    scout_export(n) -> save raw JSON + field doc

  Full scan (when no keyword):
    scout_open(url) -> scout_act("search", kw) -> scout_scan(mode="all")
    -> scout_apis() -> scout_inspect(n) -> scout_export(n)

  SSR pages: scout_apis() returns 0 is normal, use scout_search + scout_scan(mode="dom")

  Other tools:
    scout_fetch() get full page text + links
    scout_elements() list clickable elements and DOM containers
    scout_click(n) click element by ID
    scout_login() wait for manual login
    scout_screenshot() capture page screenshot
    scout_tabs() / scout_tab_switch(n) / scout_tab_close(n) manage tabs
    scout_peek(url, path_contains="...") one-shot API discovery
    scout_scan(mode="dom", keyword="...") keyword-targeted DOM scan
    scout_export_all() batch export all APIs
    scout_close() close browser and clear all data

FETCH RULE: JS-rendered pages need scout_fetch() for browser-rendered text. Static
HTML pages can use other fetch tools.
""")

# Inject mcp into state so tool modules can register themselves
state.mcp = mcp

# Import tool modules to register all tools
import web_scout.tools.navigate   # noqa: E402, F401
import web_scout.tools.observe    # noqa: E402, F401
import web_scout.tools.act        # noqa: E402, F401
import web_scout.tools.discover   # noqa: E402, F401
import web_scout.tools.scan       # noqa: E402, F401


def main():
    mcp.run()


if __name__ == "__main__":
    main()
