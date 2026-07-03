"""Navigate tools — browser lifecycle & tab management."""

import time as _time

from web_scout import state
from web_scout.browser import BrowserSession
from web_scout.network_pool import NetworkPool


@state.mcp.tool()
def scout_open(url: str, reuse: bool = False) -> str:
    """Open a URL in Chromium, extract full page text and interactive elements.

    Starts network monitoring and captures initial API requests automatically.
    After open, use scout_search(keyword) with keywords from the page text to
    locate data sources. No need to call scout_scan() unless you want
    DOM container information.

    Args:
        url: Target website URL.
        reuse: False = new_env() clean session; True = keep existing browser.

    Returns:
        Page title, tab context, and full markdown text.
    """
    # 清理接管来的旧浏览器（除非明确要复用）
    if not reuse:
        if state._browser and state._browser._browser:
            try:
                if state._browser._browser.states.is_existed:
                    state._browser._browser.quit(timeout=3, force=True)
            except Exception:
                pass
            state._browser = None
            state.set_pool(None)
            state._dom_scanners.clear()
            state._login = None
            state._login_pending = False

    if not state._browser:
        state._browser = BrowserSession(force_new=not reuse)

    pool = state.get_pool()
    if not pool:
        pool = NetworkPool()
        state.set_pool(pool)

    # 先监听, 再导航
    tab = state._browser.get_current_tab()
    pool.start_tab(tab)

    try:
        result = state._browser.open(url)
    except Exception as e:
        return f"Failed to open page: {e}"

    tab_id = result["tab_id"]

    _time.sleep(3)
    pool.step(timeout=8.0, tab=tab)

    elements = _ax_summary(state._browser.get_current_tab())

    return "\n".join([
        state.prefix(tab_id),
        f"Page opened: {result['title'] or url}",
        "",
        "=== Page Text ===",
        result["text"],
        "",
        "=== Elements ===",
        elements,
    ])


def _ax_summary(tab) -> str:
    """Extract visible interactive elements from AXTree with URLs."""
    try:
        result = tab.run_cdp('Accessibility.getFullAXTree')
        nodes = result.get('nodes', [])
        lines = []
        for n in nodes:
            if n.get('ignored', False):
                continue
            name = n.get('name', {}).get('value', '')
            if not name or len(name) < 2:
                continue
            role = n.get('role', {}).get('value', '')
            url = ''
            for p in n.get('properties', []):
                if p.get('name') == 'url':
                    url = p.get('value', {}).get('value', '')
                    break
            if url:
                lines.append(f'[{role}] {name} -> {url}')
            else:
                lines.append(f'[{role}] {name}')
        return '\n'.join(lines)
    except Exception:
        return "(AXTree unavailable)"


@state.mcp.tool()
def scout_close() -> str:
    """Close the entire browser and clear all captured data.

    Returns:
        Status message.
    """
    if state._browser:
        state._browser.close()
        state._browser = None
    state.set_pool(None)
    state._dom_scanners.clear()
    state._login = None
    state._exporter = None
    return "Browser closed. All data cleared."


@state.mcp.tool()
def scout_tabs() -> str:
    """List all open browser tabs with CDP short IDs.

    Returns:
        Tab list with short IDs and current marker.
    """
    if not state._browser:
        return "No browser session. Call scout_open first."
    return state._browser.list_tabs()


@state.mcp.tool()
def scout_tab_switch(tab: str) -> str:
    """Switch the active tab by CDP short ID (from scout_tabs output).

    After switching, observe/act tools target the new tab.

    Args:
        tab: CDP short ID (first 8 chars, from scout_tabs output).

    Returns:
        Status with the new tab's URL.
    """
    if not state._browser:
        return "No browser session. Call scout_open first."

    result = state._browser.switch_tab(tab)
    if "not found" in result:
        return result
    tid = state._browser.current_tab_id()
    return f"{result}\n{state.prefix(tid)}"


@state.mcp.tool()
def scout_tab_close(tab: str = "") -> str:
    """Close a browser tab and clean up its captured data.

    Args:
        tab: CDP short ID to close. Empty = current tab.

    Returns:
        Status message.
    """
    if not state._browser:
        return "No browser session. Call scout_open first."

    tid = tab if tab else state._browser.current_tab_id()
    result = state._browser.close_tab(tid)

    pool = state.get_pool()
    if pool:
        pool.prune(state._browser.resolve_tab_id(tid) or tid)

    state._dom_scanners.pop(state._browser.resolve_tab_id(tid) or tid, None)

    if not state._browser._browser or not state._browser._browser.tab_ids:
        state.set_pool(None)
        state._dom_scanners.clear()
    return result
