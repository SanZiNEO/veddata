"""Observe tools — read current page state."""

import json
import os
import time

from web_scout import state
from web_scout.dom import DOMScanner


@state.mcp.tool()
def scout_fetch(max_length: int = 5000, start_index: int = 0, tab: str = "") -> str:
    """Fetch full page content — scrolls to bottom, dumps innerText + AXTree links,
    writes to cache file, returns chunked segments.

    First call scrolls to bottom and writes a JSON cache file.
    Subsequent calls with start_index read from cache (no re-scroll).

    Args:
        max_length: Characters per chunk (default 5000).
        start_index: Start position (default 0).
        tab: CDP short ID (empty = current active tab).

    Returns:
        Page text segment with links in range.
    """
    if not state._browser:
        return "Error: call scout_open first."

    tab_id = state._browser.resolve_tab_id(tab) or state._browser.current_tab_id()
    tab_obj = state._browser.get_tab_by_id(tab_id)

    save_dir = os.environ.get('RESPONSE_DIR', './response')
    cache_path = f"{save_dir}/fetch_{tab_id[:8]}.json"
    os.makedirs(save_dir, exist_ok=True)

    if not os.path.exists(cache_path):
        tab_obj.scroll.to_bottom()
        time.sleep(1.5)

        text = tab_obj.run_js("return document.body.innerText || ''")
        if not isinstance(text, str):
            text = ""

        ax = tab_obj.run_cdp('Accessibility.getFullAXTree')
        links = []
        for n in ax.get('nodes', []):
            if n.get('ignored', False):
                continue
            if n.get('role', {}).get('value') != 'link':
                continue
            name = n.get('name', {}).get('value', '')
            if not name or name.startswith('javascript:'):
                continue
            url = ''
            for p in n.get('properties', []):
                if p.get('name') == 'url':
                    url = p.get('value', {}).get('value', '')
                    break
            if url:
                pos = text.find(name)
                if pos >= 0:
                    links.append({
                        'name': name[:10] + ('...' if len(name) > 10 else ''),
                        'url': url,
                        'pos': pos,
                    })

        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump({'text': text, 'links': links}, f)

    with open(cache_path, 'r', encoding='utf-8') as f:
        cache = json.load(f)
    text = cache['text']
    links = cache['links']

    chunk = text[start_index:start_index + max_length]
    segment_links = [
        l for l in links
        if start_index <= l['pos'] < start_index + max_length
    ]

    lines = [
        state.prefix(tab_id),
        f"({len(text)} chars total)",
        f"Title: {tab_obj.title}",
        "",
        f"=== Text ({start_index} ~ {start_index + len(chunk)}) ===",
        chunk,
    ]
    if segment_links:
        lines.append("\n=== Links in this segment ===")
        for l in segment_links:
            lines.append(f"[link] {l['name']} -> {l['url']}")
    if len(chunk) == max_length and len(text) > start_index + max_length:
        lines.append(
            f"\n... (truncated, call scout_fetch(start_index={start_index + max_length}) for more)"
        )
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
    """List interactive page elements, repeated DOM containers, and common actions.

    Scans for clickable buttons, links, inputs and detects repeated
    container structures (card layouts, list items, etc.).

    Returns:
        Numbered list of interactive elements + DOM containers + Common Actions.
    """
    if not state._browser:
        return "Error: call scout_open first."

    tab_id = state._browser.current_tab_id()
    dom = state._dom_scanners.get(tab_id)
    if not dom:
        dom = DOMScanner(state._browser.get_current_tab())
        state._dom_scanners[tab_id] = dom

    lines = [state.current_prefix(), "", dom.list_elements()]

    containers = dom.find_containers()
    if containers:
        lines.append("")
        lines.append("---")
        lines.append(containers)

    common = dom.find_common_actions()
    if common:
        lines.append("")
        lines.append("---")
        lines.append("=== Common Actions ===")
        lines.append(common)

    return "\n".join(lines)


@state.mcp.tool()
def scout_cookies(all_domains: bool = False, all_info: bool = False, tab: str = "") -> str:
    """View cookies for the current page.

    Args:
        all_domains: False = current domain only, True = all domains.
        all_info: False = name/value/domain only, True = include path/httpOnly/secure/expires.
        tab: CDP short ID (empty = current active tab).

    Returns:
        Formatted cookie list.
    """
    if not state._browser:
        return "Error: call scout_open first."

    tab_id = state._browser.resolve_tab_id(tab) or state._browser.current_tab_id()
    tab_obj = state._browser.get_tab_by_id(tab_id)
    if not tab_obj:
        return f"Tab {tab_id[:8]} not found."

    try:
        cookies = tab_obj.cookies(all_domains=all_domains, all_info=all_info)
    except Exception as e:
        return f"Failed to get cookies: {e}"

    if not cookies:
        return f"{state.prefix(tab_id)}\nNo cookies found."

    lines = [state.prefix(tab_id)]
    if all_info:
        lines.append(f"Cookies ({len(cookies)}, full info):")
        for c in cookies:
            domain = c.get("domain", "")
            name = c.get("name", "")
            value = c.get("value", "")
            parts = []
            if c.get("httpOnly"):
                parts.append("httpOnly")
            if c.get("secure"):
                parts.append("secure")
            if c.get("path"):
                parts.append(f"path={c['path']}")
            expires = c.get("expires")
            if expires:
                parts.append(f"expires={expires}")
            extra = " [" + ", ".join(parts) + "]" if parts else ""
            lines.append(f"  {name:<20} = {value:<30} ({domain}){extra}")
    else:
        lines.append(f"Cookies ({len(cookies)}, current domain):")
        for c in cookies:
            name = c.get("name", "")
            value = c.get("value", "")
            domain = c.get("domain", "")
            lines.append(f"  {name:<20} = {value:<30} ({domain})")

    return "\n".join(lines)
