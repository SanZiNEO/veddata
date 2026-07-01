"""Web Scout MCP Server — Entry Point with 10 tools."""

import os

from fastmcp import FastMCP

from web_scout.browser import BrowserSession
from web_scout.monitor import NetworkMonitor
from web_scout.dom import DOMScanner
from web_scout.login import LoginDetector
from web_scout.export import Exporter

mcp = FastMCP("web-scout", instructions="""
Web Scout is a DATA SOURCE DISCOVERY tool, not a scraper or browser automation tool.

WHAT IT DOES:
- Opens web pages in a real browser → extracts text + captures API requests + scans DOM structure
- Outputs compressed field documentation for AI to write scrapers from
- Detects login walls and guides users through manual login

WHAT IT DOES NOT DO:
- Execute JavaScript, modify request headers, or manage cookies
- Scrape or download data — this is a reconnaissance tool
- Replace Chrome DevTools snapshot — DevTools shows detailed element trees for humans;
  Web Scout outputs compressed container summaries optimized for AI token consumption

EXPECTED WORKFLOW:
  1. scout_open(url) → read page text first
  2. AI reads text to decide if page is usable
  3. scout_analyze() → capture APIs + scan DOM + extract embedded JSON (only when needed)
  4. scout_list_apis() → see captured endpoints
  5. scout_inspect_api(n) → view request params + response structure
  6. scout_export(n) → save raw JSON + field documentation

For DOM-heavy pages: scout_list_elements() → find containers → scout_inspect_dom()
For quick verification: scout_fetch_api(url, path) — open + capture + return in one call.
""")

_response_dir = os.environ.get("RESPONSE_DIR", "./response")
if os.path.exists(_response_dir):
    import shutil
    shutil.rmtree(_response_dir)

_browser: BrowserSession | None = None
_monitor: NetworkMonitor | None = None
_dom: DOMScanner | None = None
_login: LoginDetector | None = None
_exporter: Exporter | None = None

_login_pending: bool = False


@mcp.tool()
def scout_open(url: str) -> str:
    """Open a URL in Chromium, extract full page text as Markdown.

    Returns page title and full markdown text. No API monitoring or DOM
    scanning is performed — call scout_analyze() after reading the text if
    you need to inspect API endpoints or DOM containers.

    Args:
        url: Target website URL.

    Returns:
        Page title and full markdown text.
    """
    global _browser, _monitor, _dom, _login, _exporter, _login_pending

    if _login_pending and _browser:
        login = LoginDetector(_browser.tab)
        if not login.is_login_required():
            _login_pending = False
        else:
            return ("登录未完成，请在浏览器中手动登录，然后调用 scout_wait_login()。\n"
                    "如果要换目标页面，先调用 scout_close() 关闭当前会话。")

    _monitor = None
    _dom = None
    _exporter = None

    if not _browser:
        _browser = BrowserSession()

    _monitor = NetworkMonitor(_browser.tab)
    _monitor.start()

    try:
        result = _browser.open(url)
    except Exception as e:
        return f"Failed to open page: {e}"

    _login = LoginDetector(_browser.tab)
    if _login.is_login_required():
        _login_pending = True
        title = _browser.tab.title or url
        text = _browser.get_text()
        return (f"页面已打开: {title}\n\n"
                f"=== 页面文本 ===\n{text}\n\n"
                f"⚠️ 此页面需要登录。登录后可获取完整 cookies 和更多 API 端点。\n"
                f"请在浏览器中手动登录，然后调用 scout_wait_login() 继续。")

    lines = [
        f"Page opened: {result['title'] or url}",
        "",
        "=== Page Text ===",
        result["text"],
    ]
    return "\n".join(lines)


@mcp.tool()
def scout_analyze() -> str:
    """Analyze the current page: capture API endpoints, scan DOM containers,
    and extract embedded JSON data from window globals.

    Call this AFTER reading the page text from scout_open(). This starts
    network monitoring, waits for API responses, scans the DOM for
    repeated containers, and extracts SSR-embedded JSON data.

    Returns:
        Count of APIs, DOM containers, and embedded data sources found.
    """
    global _monitor, _dom, _exporter, _browser

    if not _browser:
        return "Error: call scout_open first."

    if _login_pending:
        return "Error: call scout_wait_login() first."

    import time
    time.sleep(3)
    api_count = _monitor.wait_new(timeout=3.0) if _monitor else 0

    embedded_count = _monitor.capture_embedded_json() if _monitor else 0

    _dom = DOMScanner(_browser.tab)
    _exporter = Exporter()

    containers = _dom.find_containers()
    dom_count = len(_dom.containers_cache)

    parts = [f"Analyze complete: {api_count} APIs, {dom_count} DOM containers, {embedded_count} embedded data sources."]
    if api_count > 0 or embedded_count > 0:
        parts.append("Use scout_list_apis() to list all captured endpoints.")
    if dom_count > 0:
        parts.append("Use scout_list_elements() to list interactive elements and containers.")
    return "\n".join(parts)


@mcp.tool()
def scout_action(action: str, value: str | None = None) -> str:
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

    After executing, returns number of newly captured API endpoints and
    DOM container changes. This is how you trigger infinite-scroll pagination
    or dynamic content loading — scroll, then check scout_list_apis() for
    new endpoints.

    Args:
        action: "search" or "scroll"
        value:   For "search": the keyword to type into the search box.
                 For "scroll": scroll target (see options above). Defaults to bottom.

    Returns:
        Status message with count of new APIs and DOM changes.
    """
    global _monitor, _browser, _dom

    if not _browser:
        return "Error: call scout_open first."

    if _login_pending:
        return "Error: call scout_wait_login() first."

    if action == "search" and value:
        try:
            import time

            inputs = _browser.tab.eles(
                "css:input[type=text], css:input[type=search], css:input[placeholder*=搜索]"
            )
            if not inputs:
                inputs = _browser.tab.eles(
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
                    input_el.input(value)
                    _browser.tab.actions.press_keys("Enter")
                else:
                    return "No visible search input found. Use scout_list_elements to select manually."
            else:
                return "No input fields found."

            time.sleep(2)

            new_count = _monitor.wait_new(timeout=3.0) if _monitor else 0
            return f"Executed {action}: {value}, captured {new_count} new APIs"
        except Exception as e:
            return f"Search failed: {e}"

    elif action == "scroll":
        try:
            api_before = len(_monitor.api_records) if _monitor else 0
            dom_before = len(_dom.containers_cache) if _dom else 0

            if value is None or value == "bottom":
                _browser.tab.scroll.to_bottom()
                desc = "bottom"
            elif value == "top":
                _browser.tab.scroll.to_top()
                desc = "top"
            elif value == "down":
                vp_height = _browser.tab.run_js("return window.innerHeight")
                _browser.tab.scroll.down(vp_height)
                desc = f"down {vp_height}px (1 viewport)"
            elif value == "up":
                vp_height = _browser.tab.run_js("return window.innerHeight")
                _browser.tab.scroll.up(vp_height)
                desc = f"up {vp_height}px (1 viewport)"
            elif value.lstrip("-").isdigit():
                px = int(value)
                if px >= 0:
                    _browser.tab.scroll.down(px)
                    desc = f"down {px}px"
                else:
                    _browser.tab.scroll.up(abs(px))
                    desc = f"up {abs(px)}px"
            else:
                return f"Unsupported scroll value: '{value}'. Use 'top', 'bottom', 'down', 'up', or pixel number."

            import time
            time.sleep(2)

            new_apis = _monitor.wait_new(timeout=3.0) if _monitor else 0

            dom_new = 0
            dom_total = 0
            if _dom:
                _dom.find_containers()
                dom_total = len(_dom.containers_cache)
                dom_new = max(0, dom_total - dom_before)

            parts = [f"Scrolled to {desc}."]

            if _monitor:
                if new_apis > 0:
                    parts.append(f"{new_apis} new APIs captured (total: {len(_monitor.api_records)}).")
                else:
                    parts.append(f"0 new APIs. Total: {len(_monitor.api_records)}.")

            if _dom:
                if dom_new > 0:
                    parts.append(f"DOM: {dom_total} containers, {dom_new} new since last scan.")
                else:
                    parts.append(f"DOM: {dom_total} containers (no new).")

            return " ".join(parts)

        except Exception as e:
            return f"Scroll failed: {e}"
    else:
        return f"Unsupported action: {action}. Use 'search' or 'scroll'."


@mcp.tool()
def scout_wait_login(timeout: int = 300) -> str:
    """Wait for the user to manually log in via the browser window.

    Args:
        timeout: Maximum wait time in seconds (default 300).

    Returns:
        Status message with refreshed page text.
    """
    global _login_pending, _browser, _login

    if not _browser or not _login:
        return "Error: call scout_open first."

    result = _login.wait_for_login(timeout)

    if result:
        _login_pending = False
        text = _browser.get_text()
        return (f"登录成功！\n\n"
                f"页面文本:\n{text[:2000]}\n\n"
                f"如果需要获取 API 端点，请调用 scout_analyze()。")
    else:
        return f"Login timeout ({timeout}s). Please try again."


@mcp.tool()
def scout_list_apis(keyword: str | None = None) -> str:
    """List all captured API endpoints, optionally filtered by keyword.

    The keyword filter searches both the URL path and the full response body
    (recursively through all string fields).

    Args:
        keyword: Optional filter — only show APIs whose path or response body
            contains this keyword (case-insensitive).

    Returns:
        Numbered list of API endpoints with method, path, count, and field count.
    """
    if not _monitor:
        return "No APIs captured yet. Call scout_analyze() first after scout_open()."

    return _monitor.list_apis(keyword=keyword)


@mcp.tool()
def scout_inspect_api(index: int, detail: str = "preview") -> str:
    """Show full request and response details for a specific API.

    Args:
        index: API endpoint ID (from scout_list_apis output).
        detail: "preview" (default) = truncated summary with key headers.
                "full" = complete headers + full field structure tree.

    Returns:
        Formatted request/response details + compressed field document.
    """
    global _monitor, _exporter

    if not _monitor:
        return "No APIs captured. Call scout_analyze() first after scout_open()."

    record = _monitor.get_record(index)
    if not record:
        return _monitor.get_api(index, detail)

    inspect_text = _monitor.get_api(index, detail)

    if not _exporter:
        _exporter = Exporter()
    compact_text = _exporter.compact(record)

    parts = [inspect_text]
    if compact_text:
        parts.extend(["", "=== Field Document ===", compact_text])
    return "\n".join(parts)


@mcp.tool()
def scout_list_elements() -> str:
    """List interactive page elements and repeated DOM containers.

    Returns:
        Numbered list of clickable elements and detected containers with fields.
    """
    if not _dom:
        return "No DOM data. Call scout_analyze() first after scout_open()."

    lines = [_dom.list_elements()]

    containers = _dom.find_containers()
    if containers:
        lines.append("")
        lines.append("---")
        lines.append(containers)

    return "\n".join(lines)


@mcp.tool()
def scout_click(index: int) -> str:
    """Click a page element by its ID from scout_list_elements().

    Typical workflow:
      1. scout_list_elements() → see interactive elements with IDs
      2. scout_click(n)           → click the n-th element
      3. scout_list_apis()        → see new API endpoints triggered by the click

    Common use cases:
      - Click "next page" buttons to capture pagination API calls
      - Click tabs/filters to load different data endpoints
      - Click category links to explore different API responses

    After clicking, waits 2 seconds and returns how many new APIs were captured.

    Args:
        index: Element ID from scout_list_elements output.

    Returns:
        Status message with element clicked and count of new APIs triggered.
    """
    if not _dom:
        return "No DOM data. Call scout_analyze() first after scout_open()."

    result = _dom.click_element(index)

    import time

    time.sleep(2)

    new_count = _monitor.wait_new(timeout=3.0) if _monitor else 0

    return f"{result}, triggered {new_count} new APIs"


@mcp.tool()
def scout_search(keyword: str) -> str:
    """Search for data by keyword: try APIs first, fall back to DOM scan.

    Searches the captured API response bodies for the keyword. If no API
    matches, falls back to scanning the DOM for elements containing the
    keyword, grouped by parent container.

    Args:
        keyword: Search term.

    Returns:
        API results or DOM keyword scan results.
    """
    if not _monitor or not _dom:
        return "No data. Call scout_analyze() first after scout_open()."

    result = _monitor.list_apis(keyword=keyword)
    if result and result != "No APIs captured yet.":
        lines = ["=== API Results ===", result]
        lines.append("")
        lines.append("Use scout_inspect_api(index) to inspect, scout_export(index) to export.")
        return "\n".join(lines)

    dom_result = _dom.scan_by_keyword(keyword)
    lines = ["=== No API match. DOM keyword scan: ===", "", dom_result]
    return "\n".join(lines)


@mcp.tool()
def scout_export(index: int, format: str = "both") -> str:
    """Export a captured API data source.

    Args:
        index: API endpoint ID (from scout_list_apis output).
        format: "raw" | "compact" | "both" (default "both").

    Returns:
        Export result with saved file path and/or field document.
    """
    global _monitor, _exporter, _browser

    if not _monitor:
        return "No data to export. Call scout_analyze() first after scout_open()."

    if not _exporter:
        _exporter = Exporter()

    record = _monitor.get_record(index)
    if not record:
        return f"API #{index} not found."

    result = _exporter.export(record, format)

    if os.environ.get("AUTO_CLOSE", "true") == "true":
        try:
            _browser.close()
        except Exception:
            pass

    return result


@mcp.tool()
def scout_export_all(format: str = "both") -> str:
    """Export all captured API data sources at once.

    Iterates through every captured API endpoint and exports each one
    to the response/ directory. Much faster than calling scout_export()
    multiple times when you have many endpoints.

    Args:
        format: "raw" | "compact" | "both" (default "both").

    Returns:
        Summary of how many APIs were exported and the output directory.
    """
    global _monitor, _exporter

    if not _monitor:
        return "No data to export. Call scout_analyze() first after scout_open()."

    if not _exporter:
        _exporter = Exporter()

    records = _monitor.api_records + _monitor.embedded_records
    if not records:
        return "No APIs captured yet."

    results = []
    for record in records:
        try:
            _exporter.export(record, format)
            results.append(f"  [{record['id']}] {record['method']} {record['path']}  → exported")
        except Exception as e:
            results.append(f"  [{record['id']}] {record['method']} {record['path']}  → FAILED: {e}")

    lines = [
        f"Batch export complete: {len(results)} APIs exported.",
        f"Output directory: {_exporter.response_dir}/",
        "",
    ]
    lines.extend(results)
    return "\n".join(lines)


@mcp.tool()
def scout_fetch_api(
    url: str, path_contains: str | None = None, method: str | None = None
) -> str:
    """Open a page, find the first JSON API matching path_contains, return full details.

    One-step verification tool: opens browser, listens for APIs, matches by path
    and method, returns inspect output + compressed field document.
    Does NOT require calling scout_open first — self-contained.

    Args:
        url: Target page URL.
        path_contains: Optional API path filter (e.g. "/search/notes").
        method: Optional HTTP method filter ("GET" or "POST").

    Returns:
        API inspect details and field document, or list of captured APIs if no match.
    """
    import time

    try:
        browser = BrowserSession()
        monitor = NetworkMonitor(browser.tab)
        monitor.start()

        browser.open(url)
        time.sleep(3)

        monitor.wait_new(timeout=5.0)

        if not monitor.api_records:
            browser.close()
            return "No JSON API requests were captured on this page."

        if path_contains:
            matches = [
                r
                for r in monitor.api_records
                if path_contains.lower() in r["path"].lower()
            ]
            if method:
                matches = [r for r in matches if r["method"].upper() == method.upper()]
        else:
            matches = monitor.api_records[:1]

        if not matches:
            lines = [
                f"No API matching path='{path_contains}'"
                + (f" method={method}" if method else "")
                + ".",
                f"Captured {len(monitor.api_records)} APIs:",
                "",
                monitor.list_apis(),
            ]
            browser.close()
            return "\n".join(lines)

        target = matches[0]
        exporter = Exporter()
        inspect_text = monitor.get_api(target["id"])
        compact_text = exporter.compact(target)

        auto_close = os.environ.get("AUTO_CLOSE", "true") == "true"
        if auto_close:
            browser.close()

        parts = [
            f"=== Matched API #{target['id']} ===",
            inspect_text,
            "",
            "=== Field Document ===",
            compact_text,
        ]
        return "\n".join(parts)

    except Exception as e:
        try:
            browser.close()
        except Exception:
            pass
        return f"scout_fetch_api failed: {e}"


@mcp.tool()
def scout_inspect_dom(url: str, keyword: str) -> str:
    """Open a page and scan DOM for containers matching keyword.

    One-step verification tool: opens browser, waits for DOM to stabilize,
    runs scan_by_keyword, returns matched containers with fields.
    Does NOT require calling scout_open first — self-contained.

    Args:
        url: Target page URL.
        keyword: Search keyword to find in DOM elements.

    Returns:
        Container list with hit counts and sample values.
    """
    import time

    try:
        browser = BrowserSession()
        browser.open(url)
        time.sleep(2)

        dom = DOMScanner(browser.tab)
        result = dom.scan_by_keyword(keyword)

        auto_close = os.environ.get("AUTO_CLOSE", "true") == "true"
        if auto_close:
            browser.close()

        return result

    except Exception as e:
        try:
            browser.close()
        except Exception:
            pass
        return f"scout_inspect_dom failed: {e}"


@mcp.tool()
def scout_close(port: int | None = None) -> str:
    """Close a browser session.

    Without arguments: closes the current session tracked by scout_open.
    With a port number: closes the browser on the specified port (9222-9231),
    regardless of whether it's the "current" session.

    Args:
        port: Optional port number to close. If omitted, closes current session.

    Returns:
        Status message.
    """
    global _browser, _monitor, _dom, _login_pending

    if port is not None:
        if not 9222 <= port <= 9231:
            return f"Port {port} out of range (9222-9231)."

        from DrissionPage import Chromium, ChromiumOptions
        try:
            co = ChromiumOptions().set_address(f"127.0.0.1:{port}")
            browser = Chromium(co)
            browser.quit()
            return f"Browser on port {port} closed."
        except Exception as e:
            return f"Port {port} is already free or could not be closed: {e}"

    if not _browser:
        return "No open browser session."

    try:
        _browser.close()
    except Exception:
        pass

    _browser = None
    _monitor = None
    _dom = None
    _login_pending = False

    return "Browser closed."


@mcp.tool()
def scout_list_browsers() -> str:
    """List all running browser instances across ports 9222-9231.

    Shows each port's status: active browser (with page title + URL) or free.
    Useful for managing multiple concurrent browsing sessions and cleaning up
    stale browser processes from previous runs.

    Typical usage:
      - Call this if scout_open() fails with port conflicts
      - Call this when you suspect leftover browser processes are wasting resources
      - After listing, call scout_close(port=N) to free up specific ports

    Returns:
        Per-port status list with page info for active instances.
    """
    from DrissionPage import Chromium, ChromiumOptions

    lines = ["Running browser instances:"]
    running = 0
    for port in range(9222, 9232):
        try:
            co = ChromiumOptions().set_address(f"127.0.0.1:{port}")
            browser = Chromium(co)
            tab = browser.latest_tab
            title = tab.title[:50] if tab.title else "(no title)"
            url = tab.url[:60] if tab.url else "about:blank"
            lines.append(f"  [{port}] {title} — {url}")
            running += 1
            browser.quit()
        except Exception:
            lines.append(f"  [{port}] (free)")

    lines.append(f"\n{running} active, {10 - running} free")
    return "\n".join(lines)


@mcp.tool()
def scout_screenshot(name: str = "screenshot", full_page: bool = True) -> str:
    """Take a screenshot of the current page.

    Args:
        name: Base filename (without extension). Default "screenshot".
        full_page: True = entire page, False = visible viewport.

    Returns:
        File path of the saved screenshot.
    """
    global _browser

    if not _browser:
        return "Error: call scout_open first."

    try:
        path = _browser.tab.get_screenshot(name=f"{name}.png", full_page=full_page)
        return f"Screenshot saved: {path}"
    except Exception as e:
        return f"Screenshot failed: {e}"


def main():
    mcp.run()


if __name__ == "__main__":
    main()
