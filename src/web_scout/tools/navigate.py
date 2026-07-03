"""Navigate tools — browser lifecycle, tab management, navigation."""

import time as _time

from web_scout import state
from web_scout.browser import BrowserSession
from web_scout.network_pool import NetworkPool


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
def scout_open() -> str:
    """Open / manage the browser session.

    Finds or launches a Chromium on port 9222.  Clears old tabs and resets
    the API pool.  Does NOT navigate — use scout_goto() for that.

    Returns:
        Browser session status.
    """
    # 清理接管来的旧浏览器
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

    if not state._browser:
        state._browser = BrowserSession()

    pool = state.get_pool()
    if not pool:
        pool = NetworkPool()
        state.set_pool(pool)

    # 确保有一个空白标签页
    browser = state._browser._ensure_browser()
    for tid in browser.tab_ids:
        try:
            tab = browser.get_tab(tid)
            tab_url = str(tab.url or "")
            if tab_url in ("about:blank", "", "chrome://newtab/"):
                state._browser._register_tab(tab)
                break
        except Exception:
            continue
    else:
        tab = browser.new_tab()
        state._browser._register_tab(tab)

    return "Browser ready. Call scout_goto(url) to navigate."


@state.mcp.tool()
def scout_goto(url: str, new_tab: bool = False) -> str:
    """Navigate to a URL and capture API requests.

    Starts network monitoring BEFORE navigating (required: listen.start()
    must precede any action that triggers requests).  Returns page text
    and interactive elements.

    Use new_tab=True to open in a new tab while keeping the current page.

    Args:
        url: Target URL to navigate to.
        new_tab: True = create new tab; False = navigate current tab.

    Returns:
        Page title, tab context, AXTree elements, and captured API summary.
    """
    if not state._browser:
        return "Error: call scout_open first."

    pool = state.get_pool()
    if not pool:
        pool = NetworkPool()
        state.set_pool(pool)

    if new_tab:
        browser = state._browser._ensure_browser()
        tab = browser.new_tab()
        state._browser._register_tab(tab)
    else:
        tab = state._browser.get_current_tab()

    tab_id = tab.tab_id
    pool.start_tab(tab)

    try:
        tab.get(url)
    except Exception as e:
        return f"Failed to navigate: {e}"

    _time.sleep(3)
    pool.step(timeout=8.0, tab=tab)

    # 获取页面标题和内文
    title = tab.title or ""
    text = tab.run_js("return document.body.innerText || ''") or ""
    elements = _ax_summary(tab)

    # 刚捕获的 API 摘要
    records = pool.get_by_tab(tab_id)
    api_summary = "\n".join(
        f"  [{r['id']}] {r['method']} {r['path']}  {r['count']} time{'s' if r['count'] > 1 else ''} → {r['field_count']} fields"
        for r in records[:8]
    )
    if len(records) > 8:
        api_summary += f"\n  ... and {len(records) - 8} more"

    return "\n".join([
        state.prefix(tab_id),
        f"Title: {title}",
        "",
        "=== Page Text ===",
        (text[:2000] + "\n... (truncated)" if len(text) > 2000 else text),
        "",
        f"=== Captured APIs ({len(records)}) ===",
        api_summary,
        "",
        "=== Elements ===",
        elements,
    ])


@state.mcp.tool()
def scout_close() -> str:
    """Close the browser and clear all captured data.

    Kills the Chromium process on port 9222 and resets all state.

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

    After switching, scout_goto() targets the new tab.

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
    """Close browser tab(s) by CDP short ID and prune their API records.

    Supports comma-separated IDs for batch close (e.g. "C724404D,5FD84E84").
    Empty = close current tab.

    Args:
        tab: CDP short ID(s), comma-separated. Empty = current tab.

    Returns:
        Status message.
    """
    if not state._browser:
        return "No browser session. Call scout_open first."

    tab_ids_to_close = [t.strip() for t in tab.split(",") if t.strip()] if tab else [state._browser.current_tab_id()]
    pool = state.get_pool()
    results = []

    for short_id in tab_ids_to_close:
        tid = state._browser.resolve_tab_id(short_id) or short_id
        result = state._browser.close_tab(short_id)
        results.append(f"{result}")
        if pool:
            pool.prune(tid)
        state._dom_scanners.pop(tid, None)

    return "\n".join(results) if len(results) > 1 else results[0]
