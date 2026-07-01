"""Act tools — page interaction: search, scroll, click, login."""

import time

from web_scout import state
from web_scout.dom import DOMScanner
from web_scout.login import LoginDetector


@state.mcp.tool()
def scout_act(action: str, value: str | None = None, container: str | None = None) -> str:
    """Execute an action on the page: search or scroll.

    SEARCH:
      Finds a visible search input field, types the keyword, and presses Enter.
      Useful for triggering search-related API requests on SPA sites.

    SCROLL:
      Scrolls the page to load more content or reveal new elements.
      Supports these values:
        - omitted / "bottom" : scroll to page bottom (trigger lazy-load APIs)
        - "top"               : scroll to page top
        - "down"              : scroll down one viewport height
        - "up"                : scroll up one viewport height
        - "300"               : scroll down exactly 300px
        - "-200"              : scroll up exactly 200px

    After executing, waits for new API requests to arrive and returns the
    count of newly captured endpoints. Use this to trigger searches, scrolls,
    or other interactions that produce API calls — new requests are
    automatically captured and available via scout_apis() / scout_search().

    Args:
        action: "search" or "scroll"
        value:   For "search": the keyword to type into the search box.
                 For "scroll": scroll target (see options above). Defaults to bottom.

    Returns:
        Status message with count of new APIs and DOM changes.
    """
    if not state._browser:
        return "Error: call scout_open first."

    if state._login_pending:
        return "Error: call scout_login() first."

    tab_num = state._browser.tab_num()
    monitor = state._monitors.get(tab_num)
    dom = state._dom_scanners.get(tab_num)

    if action == "search" and value:
        try:
            inputs = state._browser.get_current_tab().eles(
                "css:input[type=text], css:input[type=search], css:input[placeholder*=搜索]"
            )
            if not inputs:
                inputs = state._browser.get_current_tab().eles(
                    "css:input:not([type=hidden]):not([type=submit])"
                )

            if inputs:
                input_el = None
                for inp in inputs:
                    try:
                        if inp.states.is_displayed:
                            input_el = inp
                            break
                    except Exception:
                        continue

                if input_el:
                    input_el.clear()
                    input_el.input(value + '\n')
                else:
                    return "No visible search input found. Use scout_elements to select manually."
            else:
                return "No input fields found."

            time.sleep(2)

            new_count = monitor.step(timeout=5.0).__len__() if monitor else 0
            return f"{state.current_prefix()}\nExecuted {action}: {value}, captured {new_count} new APIs"
        except Exception as e:
            return f"Search failed: {e}"

    elif action == "scroll":
        try:
            api_before = len(monitor.api_records) if monitor else 0
            dom_before = len(dom.containers_cache) if dom else 0
            counts_snapshot = monitor.get_count_snapshot() if monitor else {}

            if value is None or value == "bottom":
                if container:
                    state._browser.get_current_tab().run_js(f"var el=document.querySelector('{container}');if(el)el.scrollTo(0,el.scrollHeight);")
                else:
                    state._browser.get_current_tab().scroll.to_bottom()
                desc = f"bottom (container: {container})" if container else "bottom"
            elif value == "top":
                if container:
                    state._browser.get_current_tab().run_js(f"var el=document.querySelector('{container}');if(el)el.scrollTo(0,0);")
                else:
                    state._browser.get_current_tab().scroll.to_top()
                desc = f"top (container: {container})" if container else "top"
            elif value == "down":
                if container:
                    vp = state._browser.get_current_tab().run_js(f"(function(){{var el=document.querySelector('{container}');return el?el.clientHeight:window.innerHeight;}})()")
                    state._browser.get_current_tab().run_js(f"var el=document.querySelector('{container}');if(el)el.scrollBy(0,{vp});")
                else:
                    vp = state._browser.get_current_tab().run_js("return window.innerHeight")
                    state._browser.get_current_tab().scroll.down(vp)
                desc = f"down {vp}px{' (container)' if container else ''}"
            elif value == "up":
                if container:
                    vp = state._browser.get_current_tab().run_js(f"(function(){{var el=document.querySelector('{container}');return el?el.clientHeight:window.innerHeight;}})()")
                    state._browser.get_current_tab().run_js(f"var el=document.querySelector('{container}');if(el)el.scrollBy(0,-{vp});")
                else:
                    vp = state._browser.get_current_tab().run_js("return window.innerHeight")
                    state._browser.get_current_tab().scroll.up(vp)
                desc = f"up {vp}px{' (container)' if container else ''}"
            elif value.lstrip("-").isdigit():
                px = int(value)
                if container:
                    state._browser.get_current_tab().run_js(f"var el=document.querySelector('{container}');if(el)el.scrollBy(0,{px});")
                elif px >= 0:
                    state._browser.get_current_tab().scroll.down(px)
                else:
                    state._browser.get_current_tab().scroll.up(abs(px))
                desc = f"{'down' if px >= 0 else 'up'} {abs(px)}px{' (container)' if container else ''}"
            else:
                return f"Unsupported scroll value: '{value}'. Use 'top', 'bottom', 'down', 'up', or pixel number."

            time.sleep(2)

            new_apis = len(monitor.step(timeout=5.0)) if monitor else 0
            recurring = monitor.recurring_since(counts_snapshot) if monitor else []

            dom_new = 0
            dom_total = 0
            if dom:
                dom.find_containers()
                dom_total = len(dom.containers_cache)
                dom_new = max(0, dom_total - dom_before)

            parts = [state.current_prefix(), f"Scrolled to {desc}."]

            if monitor:
                parts.append(f"{new_apis} new, {len(recurring)} recurring, {len(monitor.api_records)} total APIs.")
                if recurring:
                    parts.append("Recurring (likely pagination/feed):")
                    for rec in recurring[:5]:
                        parts.append(f"  [{rec['id']}] {rec['method']} {rec['path']} x{rec['count']}")

            if dom:
                if dom_new > 0:
                    parts.append(f"DOM: {dom_total} containers, {dom_new} new since last scan.")
                else:
                    parts.append(f"DOM: {dom_total} containers (no new).")

            return "\n".join(parts)

        except Exception as e:
            return f"Scroll failed: {e}"
    else:
        return f"Unsupported action: {action}. Use 'search' or 'scroll'."


@state.mcp.tool()
def scout_click(index: int) -> str:
    """Click a page element by its ID from scout_elements().

    Typical workflow:
      1. scout_elements() → see interactive elements with IDs
      2. scout_click(n)           → click the n-th element
      3. scout_apis()        → see new API endpoints triggered by the click

    Common use cases:
      - Click "next page" buttons to capture pagination API calls
      - Click tabs/filters to load different data endpoints
      - Click category links to explore different API responses

    After clicking, waits 2 seconds and returns how many new APIs were captured.

    Args:
        index: Element ID from scout_elements output.

    Returns:
        Status message with element clicked and count of new APIs triggered.
    """
    if not state._browser:
        return "Error: call scout_open first."

    tab_num = state._browser.tab_num()
    dom = state._dom_scanners.get(tab_num)
    if not dom:
        return "No DOM data. Call scout_scan(mode='all') or scout_elements() first."

    result = dom.click_element(index)
    time.sleep(2)

    monitor = state._monitors.get(tab_num)
    new_count = monitor.wait_new(timeout=3.0) if monitor else 0

    return f"{state.current_prefix()}\n{result}, triggered {new_count} new APIs"


@state.mcp.tool()
def scout_login(timeout: int = 300) -> str:
    """Wait for the user to manually log in via the browser window.

    Args:
        timeout: Maximum wait time in seconds (default 300).

    Returns:
        Status message with refreshed page text.
    """
    if not state._browser or not state._login:
        return "Error: call scout_open first."

    if not state._login.is_login_required():
        state._login_pending = False
        text = state._browser.get_text()
        return (f"{state.current_prefix()}\n"
                f"Already logged in, no wait needed.\n\n"
                f"Page text:\n{text[:2000]}\n\n"
                f"Call scout_scan(mode='all') to capture API endpoints.")

    result = state._login.wait_for_login(timeout)

    if result:
        state._login_pending = False
        text = state._browser.get_text()
        return (f"{state.current_prefix()}\n"
                f"Login successful!\n\n"
                f"Page text:\n{text[:2000]}\n\n"
                f"Call scout_scan(mode='all') to capture API endpoints.")
    else:
        return f"Login timeout ({timeout}s). Please try again."
