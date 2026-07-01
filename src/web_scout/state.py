"""Shared state and helper functions for Web Scout tools."""

from web_scout.browser import BrowserSession
from web_scout.monitor import NetworkMonitor
from web_scout.dom import DOMScanner
from web_scout.login import LoginDetector
from web_scout.export import Exporter

_browser: BrowserSession | None = None
_monitors: dict[int, NetworkMonitor] = {}
_dom_scanners: dict[int, DOMScanner] = {}
_login: LoginDetector | None = None
_exporter: Exporter | None = None
_login_pending: bool = False
_response_dir: str | None = None

# MCP instance — injected by server.py before tool modules are imported
from fastmcp import FastMCP
mcp: FastMCP = None  # type: ignore


def resolve_tab(tab: int = 0) -> tuple[int, NetworkMonitor | None, DOMScanner | None]:
    """Resolve tab number and associated monitor/dom_scanner.

    tab=0 → current active tab's display number.
    tab=N → display number N.

    Returns:
        (tab_num, monitor_or_None, dom_scanner_or_None)
    """
    if not _browser:
        return (0, None, None)
    if tab == 0:
        tab_num = _browser.tab_num()
    else:
        tab_num = tab
    return (tab_num, _monitors.get(tab_num), _dom_scanners.get(tab_num))


def get_exporter(output_dir: str | None = None) -> Exporter:
    """Get or create the global Exporter instance.

    Args:
        output_dir: Override directory for this call (default _response_dir or ./response).
    """
    global _exporter
    if output_dir:
        return Exporter(response_dir=output_dir)
    if not _exporter:
        _exporter = Exporter(response_dir=_response_dir or "./response")
    return _exporter


def prefix(tab_num: int) -> str:
    """Return [Tab #N] URL context prefix for the given tab number."""
    if not _browser:
        return ""
    url = ""
    for tid, info in _browser._tabs.items():
        if info.get("num") == tab_num:
            url = (info.get("url") or "")[:60]
            break
    return f"[Tab #{tab_num}] {url}"


def current_prefix() -> str:
    """Return [Tab #N] URL context prefix for the current tab."""
    if not _browser:
        return ""
    num = _browser.tab_num()
    url = ""
    try:
        tab = _browser.get_current_tab()
        url = (tab.url or "")[:60]
    except Exception:
        pass
    return f"[Tab #{num}] {url}"
