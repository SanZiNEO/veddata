"""Observe tools — read current page state."""

import re as _re

from web_scout import state
from web_scout.dom import DOMScanner


@state.mcp.tool()
def scout_fetch(max_length: int = 5000, start_index: int = 0) -> str:
    """Fetch the visible text of the current page as a browser sees it.

    Uses document.body.innerText — returns ALL visible text including
    content below the fold AFTER you scroll to it. Does NOT strip
    navigation/footer noise. Includes page title, URL, and list of links.

    Supports chunked reading: set start_index to continue from where
    the previous call left off.

    Args:
        max_length: Maximum characters to return (default 5000, max 50000).
        start_index: Start from this character index (default 0).

    Returns:
        Title, URL, links list, and page text with tab context.
    """
    if not state._browser:
        return "Error: call scout_open first."

    try:
        title = str(state._browser.get_current_tab().title or "")
        url = str(state._browser.get_current_tab().url or "")
    except Exception:
        title, url = "", "about:blank"

    try:
        text = state._browser.get_current_tab().run_js("return document.body.innerText || ''")
        if not isinstance(text, str):
            text = ""
    except Exception:
        text = ""

    links = []
    try:
        html = state._browser.get_current_tab().html
        for m in _re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, _re.DOTALL | _re.IGNORECASE):
            href, raw_text = m.group(1), m.group(2)
            if not href or href.startswith('javascript:'):
                continue
            txt = _re.sub(r'<[^>]+>', '', raw_text).strip()[:80]
            if not txt:
                txt = href[:80]
            links.append(f'{txt} -> {href}')
            if len(links) >= 100:
                break
    except Exception:
        links = []

    lines = [
        state.current_prefix(),
        f"Title: {title}",
        f"URL:   {url}",
        "",
    ]

    if links:
        lines.append(f"=== Links ({len(links)}) ===")
        for link in links[:50]:
            lines.append(link)
        if len(links) > 50:
            lines.append(f"... and {len(links) - 50} more")
        lines.append("")

    max_len = min(max_length, 50000)
    chunk = text[start_index:start_index + max_len]
    lines.append("=== Page Text ===")
    lines.append(chunk)
    if len(chunk) == max_len and len(text) > start_index + max_len:
        lines.append(f"\n... (truncated, call scout_fetch(start_index={start_index + max_len}) for more)")

    return "\n".join(lines)


@state.mcp.tool()
def scout_screenshot(name: str = "screenshot", full_page: bool = True) -> str:
    """Take a screenshot of the current page.

    Args:
        name: Base filename (without extension). Default "screenshot".
        full_page: True = entire page, False = visible viewport.

    Returns:
        File path of the saved screenshot with tab context.
    """
    if not state._browser:
        return "Error: call scout_open first."

    try:
        path = state._browser.get_current_tab().get_screenshot(name=f"{name}.png", full_page=full_page)
        return f"{state.current_prefix()}\nScreenshot saved: {path}"
    except Exception as e:
        return f"Screenshot failed: {e}"


@state.mcp.tool()
def scout_elements() -> str:
    """List interactive page elements and repeated DOM containers.

    Scans for clickable buttons, links, inputs and detects repeated
    container structures (card layouts, list items, etc.).

    Returns:
        Numbered list of clickable elements and detected containers with fields.
    """
    if not state._browser:
        return "Error: call scout_open first."

    tab_num = state._browser.tab_num()
    dom = state._dom_scanners.get(tab_num)
    if not dom:
        dom = DOMScanner(state._browser.get_current_tab())
        state._dom_scanners[tab_num] = dom

    lines = [state.current_prefix(), "", dom.list_elements()]

    containers = dom.find_containers()
    if containers:
        lines.append("")
        lines.append("---")
        lines.append(containers)

    return "\n".join(lines)
