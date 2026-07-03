"""Web Scout MCP Server v0.3 — Entry point with 20 tools."""

import os

from fastmcp import FastMCP

from web_scout import state
from web_scout.browser import BrowserSession
from web_scout.network_pool import NetworkPool
from web_scout.dom import DOMScanner
from web_scout.login import LoginDetector
from web_scout.export import Exporter
from web_scout.requester import exec_request

_response_dir = os.environ.get("RESPONSE_DIR", "./response")
state._response_dir = _response_dir
if os.path.exists(_response_dir):
    import shutil
    shutil.rmtree(_response_dir)

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
    scout_open(url) -> scout_act(actions=[...]) -> scout_scan(mode="all")
    -> scout_apis() -> scout_inspect(n) -> scout_export(n)

  SSR pages: scout_apis() returns 0 is normal, use scout_search + scout_scan(mode="dom")

  Other tools:
    scout_fetch() get full page text + links (scroll-to-bottom, AXTree, cache)
    scout_elements() list clickable elements, DOM containers, Common Actions
    scout_act() chain: input/scroll/click/select, reports API paths inline
    scout_cookies() view cookies (current domain/all, summary/full info)
    scout_request() test HTTP requests (replay from captured API or custom)
    scout_login() wait for manual login
    scout_screenshot() capture page screenshot
    scout_tabs() / scout_tab_switch(tab) / scout_tab_close(tab) manage tabs
    scout_peek(url, path_contains="...") one-shot API discovery
    scout_scan(mode="dom", keyword="...") keyword-targeted DOM scan
    scout_export_all() batch export all APIs
    scout_close() close browser and clear all data

TAB IDs: All tabs use CDP short IDs (first 8 chars). scout_tab_switch(tab) uses prefix matching.
""")

state.mcp = mcp

import web_scout.tools.navigate
import web_scout.tools.observe
import web_scout.tools.act
import web_scout.tools.discover
import web_scout.tools.scan


def main():
    mcp.run()


if __name__ == "__main__":
    main()
