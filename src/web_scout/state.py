"""Shared state and helper functions for Web Scout tools."""

from web_scout.browser import BrowserSession
from web_scout.network_pool import NetworkPool
from web_scout.dom import DOMScanner
from web_scout.login import LoginDetector
from web_scout.export import Exporter

_browser: BrowserSession | None = None
_api_pool: NetworkPool | None = None
_dom_scanners: dict[str, DOMScanner] = {}
_login: LoginDetector | None = None
_exporter: Exporter | None = None
_response_dir: str | None = None

from fastmcp import FastMCP
mcp: FastMCP = None


def get_pool() -> NetworkPool | None:
    global _api_pool
    return _api_pool


def set_pool(pool: NetworkPool | None):
    global _api_pool
    _api_pool = pool


def resolve_tab_str(tab: str = "") -> tuple[str, list, DOMScanner | None]:
    """Resolve tab short-ID → (full_tab_id, api_records_for_tab, dom_scanner).

    tab="" → current active tab.
    """
    if not _browser:
        return ("", [], None)
    tab_id = _browser.resolve_tab_id(tab)
    pool = get_pool()
    records = pool.get_by_tab(tab_id) if pool else []
    dom = _dom_scanners.get(tab_id)
    return (tab_id, records, dom)


def prefix(tab_id_str: str) -> str:
    """Return [XXXX] URL context prefix for a tab short-ID."""
    if not _browser:
        return ""
    url = _browser.get_tab_url(tab_id_str)
    short = tab_id_str[:8] if tab_id_str else "?"
    return f"[{short}] {url}"


def current_prefix() -> str:
    """Return prefix for the current tab."""
    if not _browser:
        return ""
    tid = _browser.current_tab_id()
    url = _browser.get_tab_url(tid)
    short = tid[:8] if tid else "?"
    return f"[{short}] {url}"


def get_exporter(output_dir: str | None = None) -> Exporter:
    global _exporter
    if output_dir:
        return Exporter(response_dir=output_dir)
    if not _exporter:
        _exporter = Exporter(response_dir=_response_dir or "./response")
    return _exporter
