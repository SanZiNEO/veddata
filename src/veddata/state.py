"""Shared state and helper functions for veddata tools."""

from veddata.browser import BrowserSession
from veddata.network_monitor import NetworkMonitor
from veddata.dom import DOMTree
from veddata.scripts import ScriptRegistry
from veddata.export import Exporter

_browser: BrowserSession | None = None
_api_pool: NetworkMonitor | None = None
_dom_trees: dict[str, DOMTree] = {}
_script_registries: dict[str, ScriptRegistry] = {}
_watches: dict[str, object] = {}          # tab_id → WatchEngine（按需创建）
_exporter: Exporter | None = None

from fastmcp import FastMCP
mcp: FastMCP = None


async def attach_page(page) -> None:
    """Wire a freshly registered page to shared capture components.

    - NetworkMonitor: 全局单例，注入 page→tab_id 反查。
    - ScriptRegistry: 每页一个，attach 后收集 scriptParsed（须在 goto 前）。
    """
    global _api_pool
    if _api_pool is None:
        _api_pool = NetworkMonitor()
    _api_pool.attach(page, lambda p: _browser._page_to_id.get(id(p)))

    tab_id = _browser._page_to_id.get(id(page))
    if tab_id and tab_id not in _script_registries:
        try:
            cdp = await page.context.new_cdp_session(page)
            registry = ScriptRegistry(page, cdp)
            await registry.attach(cdp)
            _script_registries[tab_id] = registry
        except Exception:
            pass


def get_pool() -> NetworkMonitor | None:
    global _api_pool
    return _api_pool


def set_pool(pool: NetworkMonitor | None):
    global _api_pool
    _api_pool = pool


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


def get_exporter() -> Exporter:
    """共享的导出器；实际落盘目录每次调用时决定（见 Exporter.resolve_dir）。"""
    global _exporter
    if not _exporter:
        _exporter = Exporter()
    return _exporter
