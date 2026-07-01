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
Web Scout is a DATA SOURCE DISCOVERY tool for AI agents. It uses a real Chromium
browser to open web pages, extract rendered text, capture API requests, and scan
DOM structure — then outputs compressed field documentation so you can write
scrapers. It is NOT a scraper or browser automation tool on its own.

WHAT IT DOES:
- Opens pages in a real Chromium browser (DrissionPage) → renders JS, extracts text
- Captures XHR/Fetch network requests and SSR-embedded JSON (__INITIAL_STATE__, etc.)
- Scans DOM for repeated data containers with CSS selectors and sample values
- Triggers searches, scrolls, and clicks to discover pagination/feed APIs
- Outputs compressed field documents (token-efficient) + saves raw JSON to disk
- Detects login walls and guides users through manual login with CAPTCHA handling

WHAT IT DOES NOT DO:
- Decrypt JS-obfuscated data, reverse wasm, or bypass signature algorithms
- Modify request headers, manage cookies, or forge requests
- Execute as a standalone scraper — it discovers data sources, you write the scraper

RECOMMENDED WORKFLOW:

  Fast Path (recommended — open → search → context):
    1. scout_open(url)              → read page text, pick a visible keyword
    2. scout_act("scroll")          → trigger lazy-load / feed APIs (recommendation, timeline)
    3. scout_search(keyword)        → find which API has this keyword in its response body
    4. scout_context(keyword)       → see exact field path (e.g. data.item[0].title = "...")
    → If API hit: scout_inspect(n) → request params + response structure → scout_export(n)

    Example (bilibili):
      scout_open → picks "男人领域" from text
      scout_act("scroll") → +11 APIs, hits feed/rcmd
      scout_search("男人领域") → [51] GET feed/rcmd
      scout_context("男人领域") → data.item[0].title = "男人领域"
      → Target confirmed: feed/rcmd is the recommendation API

    This skips scan/apis enumeration; search+context pinpoint the exact API+field directly.

  Full Scan (when you do not have a keyword yet):
    1. scout_open(url)              → read rendered page text, identify keywords
    2. scout_fetch()                → get full text + all links (JS-heavy SPA pages)
    3. scout_act("search", kw)      → trigger search APIs with keywords from step 1-2
    4. scout_scan(mode="all")       → capture ALL data: network APIs + SSR JSON + DOM containers
    5. scout_apis()                 → see all endpoints; [SSR] tag = embedded data
    6. scout_inspect(n)             → view request params + response structure
    7. scout_export(n)              → save raw JSON + field documentation

  Interactive Scenarios:
   - scout_elements()               → see clickable elements and DOM containers
   - scout_click(n)                 → click tabs, filters, pagination buttons
   - scout_login()                  → wait for manual login in browser window
   - scout_screenshot()             → capture visual reference of the current page
   - scout_tabs() / scout_tab_switch(n) / scout_tab_close(n) → manage multi-tab browsing

  Quick Utilities:
   - scout_scan(mode="dom", keyword="...")    → keyword-targeted DOM scan
   - scout_peek(url, path_contains="...")     → one-shot API discovery, no session

  SSR Pages (dxy.com, static HTML):
    Data is in HTML/DOM, not XHR. Use scout_search + scout_scan(mode="dom") instead.
    scout_apis() will return 0 - that is expected.

FETCH RULE: For JS-rendered pages (bilibili, xiaohongshu, zhihu, SPA), use scout_fetch() —
it captures browser-rendered text that HTTP-based fetch tools cannot see. For static
HTML pages, other fetch tools may suffice.
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
