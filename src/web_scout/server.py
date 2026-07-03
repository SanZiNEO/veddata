"""Web Scout MCP Server v0.3 — Entry point with 21 tools."""

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

TAB IDs: All tabs use CDP short IDs (first 8 chars, stable across sessions).
  scout_tab_switch("5FD84E84") — switch by short ID (prefix matched)
  scout_tab_close("5FD84E84,3B17A2F5") — comma-separated for batch close

RECOMMENDED WORKFLOW:

  Fast path (recommended):
    scout_open() -> scout_goto(url) -> pick a keyword from text
    scout_act("scroll") -> trigger feed/recommendation APIs
    scout_search(keyword) -> find which API contains it
    scout_context(keyword) -> see field path and value
    scout_inspect(n) -> request params + response structure
    scout_export(n) -> save raw JSON + field doc

  Full scan (when no keyword):
    scout_open() -> scout_goto(url) -> scout_act(actions=[...])
    -> scout_scan(mode="all") -> scout_apis() -> scout_inspect(n) -> scout_export(n)

  SSR pages: scout_apis() returns 0 is normal, use scout_search + scout_scan(mode="dom")

  One-shot API discovery (no browser session needed):
    scout_peek(url, path_contains="...") -> inspect + field doc

Tools — browser lifecycle:
  scout_open()              — find or launch Chromium on port 9222, clear old tabs
  scout_goto(url, new_tab)  — navigate, capture APIs, return text + elements + API summary
  scout_close()             — kill Chromium on port 9222, clear all data
  scout_tabs()              — list open tabs with short IDs
  scout_tab_switch(tab)     — switch active tab by short ID
  scout_tab_close(tab)      — close tab(s) by short ID, prune API records

Tools — page reading:
  scout_fetch(start_index, max_length, tab)
    — scroll to bottom, dump innerText + AXTree links, cache to file, chunked read
  scout_elements()
    — interactive elements, repeated DOM containers (v3), Common Actions
  scout_screenshot(name, full_page)
    — capture page screenshot

Tools — interaction:
  scout_act(action, value, target) or scout_act(actions=[...])
    — input/scroll/click/select chain; reports new API method + path inline
  scout_login(timeout)
    — wait for manual login via cookie change detection

Tools — API discovery:
  scout_apis(keyword, tab)         — list captured APIs, filter by keyword/tab
  scout_inspect(index, detail, tab) — request/response details + field document
  scout_search(keyword, tab)        — search keyword across APIs and DOM
  scout_context(keyword, tab)       — field paths and sample values
  scout_peek(url, path_contains)    — one-shot: open, capture, inspect matching API
  scout_request(index, url, ...)    — replay HTTP request (captured or custom)
  scout_cookies(all_domains, all_info, tab) — view cookies
  scout_scan(mode, keyword, url)    — full scan or keyword-targeted DOM scan

Tools — export:
  scout_export(index, format, tab)       — export single API (raw/compact/both)
  scout_export_all(format, tab)          — export all captured APIs
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
