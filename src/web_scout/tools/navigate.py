"""Navigate tools — browser lifecycle & tab management."""

import time as _time

from web_scout import state
from web_scout.browser import BrowserSession
from web_scout.monitor import NetworkMonitor
from web_scout.login import LoginDetector


@state.mcp.tool()
def scout_open(url: str) -> str:
    """Open a URL in Chromium, extract full page text as Markdown.

    Starts network monitoring and captures initial API requests automatically.
    After open, use scout_search(keyword) with keywords from the page text to
    locate data sources. No need to call scout_scan() unless you want
    DOM container information.

    Args:
        url: Target website URL.

    Returns:
        Page title, tab context, and full markdown text.
    """
    if state._login_pending and state._browser:
        login_detector = LoginDetector(state._browser.get_current_tab())
        if not login_detector.is_login_required():
            state._login_pending = False
        else:
            return ("Login not complete. Please log in manually in the browser, then call scout_login().\n"
                    "To switch to a different page, first call scout_tab_close().")

    if not state._browser:
        state._browser = BrowserSession()

    monitor = NetworkMonitor(state._browser.get_current_tab())
    monitor.start()

    try:
        result = state._browser.open(url)
    except Exception as e:
        return f"Failed to open page: {e}"

    tab_num = state._browser.tab_num()
    state._monitors[tab_num] = monitor
    state._dom_scanners.pop(tab_num, None)

    _time.sleep(3)
    monitor.step(timeout=8.0)

    state._login = LoginDetector(state._browser.get_current_tab())
    if state._login.is_login_required():
        state._login_pending = True
        title = state._browser.get_current_tab().title or url
        text = state._browser.get_text()
        return (f"{state.prefix(tab_num)}\n"
                f"Page opened: {title}\n\n"
                f"=== Page Text ===\n{text}\n\n"
                f"This page requires login. Please log in manually in the browser, then call scout_login().")

    return "\n".join([
        state.prefix(tab_num),
        f"Page opened: {result['title'] or url}",
        "",
        "=== Page Text ===",
        result["text"],
    ])


@state.mcp.tool()
def scout_close() -> str:
    """Close the entire browser and clear all captured data.

    This is the ONLY tool that can close the browser. After calling this,
    all tabs, captured APIs, DOM data, and login state are cleared.

    Returns:
        Status message.
    """
    if state._browser:
        state._browser.close()
        state._browser = None
    state._monitors.clear()
    state._dom_scanners.clear()
    state._login = None
    state._exporter = None
    state._login_pending = False
    return "Browser closed. All data cleared."


@state.mcp.tool()
def scout_tabs() -> str:
    """List all open browser tabs. Shows tab numbers, titles, URLs, and active indicator.

    Use this to see which tabs are open and switch between them.
    AI can reference tabs by number (e.g. "Tab #2") in other tools.

    Returns:
        Numbered list of tabs with titles and current marker.
    """
    if not state._browser:
        return "No browser session. Call scout_open first."
    return state._browser.list_tabs()


@state.mcp.tool()
def scout_tab_switch(num: int) -> str:
    """Switch the active tab to a specific tab by number.

    After switching, the new tab becomes the target for observe/act tools
    (scout_fetch, scout_screenshot, scout_elements, scout_act, scout_click).

    Args:
        num: Tab number to switch to (from scout_tabs output).

    Returns:
        Status with the new tab's URL.
    """
    if not state._browser:
        return "No browser session. Call scout_open first."

    result = state._browser.switch_tab(num)
    if "not found" in result:
        return result
    tab_num = state._browser.tab_num()
    return f"{result}\n{state.prefix(tab_num)}"


@state.mcp.tool()
def scout_tab_close(tab: int | None = None) -> str:
    """Close a browser tab and clean up its captured data.

    Without arguments: closes the current tab.
    With a tab number: closes the specified tab (e.g. tab=2).

    Args:
        tab: Optional tab number to close. If omitted, closes current tab.

    Returns:
        Status message.
    """
    if not state._browser:
        return "No browser session. Call scout_open first."

    num = tab if tab is not None else state._browser.tab_num()
    result = state._browser.close_tab(num)

    state._monitors.pop(num, None)
    state._dom_scanners.pop(num, None)

    if not state._browser._browser or not state._browser._browser.tab_ids:
        state._monitors.clear()
        state._dom_scanners.clear()
        state._login_pending = False

    return result
