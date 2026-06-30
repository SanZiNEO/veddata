"""Web Scout MCP Server — Entry Point with 8 tools."""

import os

from fastmcp import FastMCP

from web_scout.browser import BrowserSession
from web_scout.monitor import NetworkMonitor
from web_scout.dom import DOMScanner
from web_scout.login import LoginDetector
from web_scout.export import Exporter

mcp = FastMCP("web-scout", instructions="AI-powered web API & DOM discovery tool")

_response_dir = os.environ.get("RESPONSE_DIR", "./response")
if os.path.exists(_response_dir):
    import shutil
    shutil.rmtree(_response_dir)

_browser: BrowserSession | None = None
_monitor: NetworkMonitor | None = None
_dom: DOMScanner | None = None
_login: LoginDetector | None = None
_exporter: Exporter | None = None

_current_url: str = ""
_current_mode: str = "auto"
_login_pending: bool = False


@mcp.tool()
def scout_open(url: str, mode: str = "auto") -> str:
    """Open a URL in Chromium, extract page text, start network monitoring.

    Args:
        url: Target website URL.
        mode: "auto" | "api" | "dom" | "text"

    Returns:
        Page info with markdown text and next-step suggestions.
    """
    global _browser, _monitor, _dom, _login, _exporter
    global _current_url, _current_mode, _login_pending

    if _login_pending and _browser:
        login = LoginDetector(_browser.tab)
        if not login.is_login_required():
            _login_pending = False
        else:
            return ("登录未完成，请在浏览器中手动登录，然后调用 scout_wait_login()。\n"
                    "如果要换目标页面，先调用 scout_close() 关闭当前会话。")

    if _browser:
        try:
            _browser.close()
        except Exception:
            pass

    _browser = BrowserSession()
    _current_url = url
    _current_mode = mode

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

    _monitor = NetworkMonitor(_browser.tab)
    _monitor.start()

    import time
    time.sleep(3)
    api_count = _monitor.wait_new(timeout=3.0)

    _dom = DOMScanner(_browser.tab)

    _exporter = Exporter()

    lines = [
        f"Page opened: {result['title'] or url}",
        "",
        "=== Page Text ===",
        result["text"],
        "",
        f"APIs loaded on page: {api_count}",
    ]

    if mode == "api":
        lines.append("→ Next: scout_action('search', 'keyword') to find data")
    elif mode == "dom":
        lines.append("→ Next: scout_list_elements() or scout_action('search', 'keyword')")
    elif mode == "text":
        lines.append("→ Text mode — full page text returned above.")

    return "\n".join(lines)


@mcp.tool()
def scout_action(action: str, value: str | None = None) -> str:
    """Execute an action on the page (search or scroll).

    Args:
        action: "search" or "scroll"
        value: Search keyword (required for "search")

    Returns:
        Status message with count of new APIs captured.
    """
    global _monitor, _browser

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
            _browser.tab.scroll.to_bottom()
            import time

            time.sleep(2)
            new_count = _monitor.wait_new(timeout=3.0) if _monitor else 0
            return f"Scrolled to bottom, captured {new_count} new APIs"
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
    global _login_pending, _browser, _monitor, _login

    if not _browser or not _login:
        return "Error: call scout_open first."

    result = _login.wait_for_login(timeout)

    if result:
        _login_pending = False
        _monitor = NetworkMonitor(_browser.tab)
        _monitor.start()
        _dom = DOMScanner(_browser.tab)
        _exporter = Exporter()
        import time
        time.sleep(3)
        api_count = _monitor.wait_new(timeout=3.0)
        text = _browser.get_text()
        return (f"登录成功！已刷新页面\n\n"
                f"API: {api_count} 个\n\n"
                f"页面文本:\n{text[:2000]}")
    else:
        return f"Login timeout ({timeout}s). Please try again."


@mcp.tool()
def scout_list_apis(keyword: str | None = None) -> str:
    """List all captured JSON API endpoints, optionally filtered by keyword.

    The keyword filter searches both the URL path and the full response body
    (recursively through all string fields).

    Args:
        keyword: Optional filter — only show APIs whose path or response body
            contains this keyword (case-insensitive).

    Returns:
        Numbered list of API endpoints with method, path, count, and field count.
    """
    if not _monitor:
        return "Error: call scout_open first."

    return _monitor.list_apis(keyword=keyword)


@mcp.tool()
def scout_inspect_api(index: int) -> str:
    """Show full request and response details for a specific API.

    Args:
        index: API endpoint ID (from scout_list_apis output).

    Returns:
        Formatted request/response details + compressed field document.
    """
    if not _monitor:
        return "Error: call scout_open first."

    record = _monitor.get_record(index)
    if not record:
        return _monitor.get_api(index)

    inspect_text = _monitor.get_api(index)
    compact_text = _exporter.compact(record) if _exporter else ""
    
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
        return "Error: call scout_open first."

    lines = [_dom.list_elements()]

    containers = _dom.find_containers()
    if containers:
        lines.append("")
        lines.append("---")
        lines.append(containers)

    return "\n".join(lines)


@mcp.tool()
def scout_click(index: int) -> str:
    """Click a page element by its index.

    Args:
        index: Element ID from scout_list_elements output.

    Returns:
        Status message with count of new APIs triggered.
    """
    if not _dom:
        return "Error: call scout_open first."

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
        return "Error: call scout_open first."

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

    if not _monitor or not _exporter:
        return "Error: call scout_open first."

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
def scout_close() -> str:
    """Close the current browser session and release resources.

    Use this when done with discovery/export, or before switching to a
    different URL with a fresh scout_open call.
    """
    global _browser, _monitor, _dom, _login_pending

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
    

def main():
    mcp.run()


if __name__ == "__main__":
    main()
