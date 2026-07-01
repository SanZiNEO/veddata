"""Discover tools — API data discovery, inspection, search, and export."""

import json as _json
import time

from web_scout import state
from web_scout.browser import BrowserSession
from web_scout.monitor import NetworkMonitor
from web_scout.export import Exporter


@state.mcp.tool()
def scout_apis(keyword: str | None = None, tab: int = 0) -> str:
    """List all captured API endpoints, optionally filtered by keyword.

    The keyword filter searches both the URL path and the full response body
    (recursively through all string fields).

    Args:
        keyword: Optional filter — only show APIs whose path or response body
            contains this keyword (case-insensitive).
        tab: Tab number (0 = current active tab).

    Returns:
        Numbered list of API endpoints with method, path, count, and field count.
    """
    tab_num, monitor, _dom = state.resolve_tab(tab)
    if not monitor:
        return "No APIs captured yet. Call scout_open() first."

    monitor.flush()
    result = monitor.list_apis(keyword=keyword)
    return f"{state.prefix(tab_num)}\n{result}"


@state.mcp.tool()
def scout_inspect(index: int, detail: str = "preview", tab: int = 0) -> str:
    """Show full request and response details for a specific API.

    Args:
        index: API endpoint ID (from scout_apis output).
        detail: "preview" (default) = truncated summary with key headers.
                "full" = complete headers + full field structure tree.
        tab: Tab number (0 = current active tab).

    Returns:
        Formatted request/response details + compressed field document.
    """
    tab_num, monitor, _dom = state.resolve_tab(tab)
    if not monitor:
        return "No APIs captured. Call scout_open() first."

    monitor.flush()
    record = monitor.get_record(index)
    if not record:
        return f"{state.prefix(tab_num)}\n{monitor.get_api(index, detail)}"

    inspect_text = monitor.get_api(index, detail)
    exporter = state.get_exporter()
    compact_text = exporter.compact(record)

    parts = [state.prefix(tab_num), inspect_text]
    if compact_text:
        parts.extend(["", "=== Field Document ===", compact_text])
    return "\n".join(parts)


@state.mcp.tool()
def scout_search(keyword: str, tab: int = 0) -> str:
    """Search for data by keyword across ALL captured network data.

    Like browser DevTools Network Search: searches ALL response bodies
    (JSON APIs, SSR embedded JSON, page HTML source, DOM text).

    Args:
        keyword: Search term.
        tab: Tab number (0 = current active tab).

    Returns:
        Numbered list of matching data sources.
    """
    tab_num, monitor, dom = state.resolve_tab(tab)
    if not monitor:
        return "No data. Call scout_open() first."

    monitor.flush()
    lines = [state.prefix(tab_num), ""]

    # 1. JSON API records
    api_result = monitor.list_apis(keyword=keyword)
    if api_result and api_result != "No APIs captured yet.":
        lines.append("=== API Matches ===")
        lines.append(api_result)
        lines.append("")

    # 2. Page HTML source
    if state._browser:
        html = state._browser.get_current_tab().html
        if keyword.lower() in html.lower():
            lines.append(f"=== Page HTML matched === (contains '{keyword}' in source)")
            lines.append(f"URL: {state._browser.get_current_tab().url}")
            lines.append("Use scout_context() to see WHERE in the page source.")

    # 3. DOM scan
    if dom:
        dom_result = dom.scan_by_keyword(keyword)
        if dom_result and "No elements" not in dom_result:
            lines.append("")
            lines.append("=== DOM Matches ===")
            lines.append(dom_result)

    if len(lines) <= 2:
        return f"{state.prefix(tab_num)}\nNo matches for '{keyword}' in any data source."

    lines.insert(1, f'Search results for "{keyword}":')
    lines.append("")
    lines.append("Use scout_context() to see field paths and values for each match.")
    return "\n".join(lines)


@state.mcp.tool()
def scout_context(keyword: str, tab: int = 0) -> str:
    """Search all data sources for keyword, returning field paths and values.

    Args:
        keyword: Search term.
        tab: Tab number (0 = current active tab).

    Returns:
        Detailed field paths and sample values for each match.
    """
    tab_num, monitor, dom = state.resolve_tab(tab)
    if not monitor:
        return "No data. Call scout_open() first."

    monitor.flush()
    results = monitor.find_context(keyword)

    # DOM search
    if dom:
        dom_result = dom.scan_by_keyword(keyword)
        if dom_result and "No elements" not in dom_result:
            results.append({"source": "[DOM]", "field": "", "value": dom_result})

    # Page meta + HTML source search
    if state._browser:
        html = state._browser.get_current_tab().html
        kw_lower = keyword.lower()

        js = """
        var kw = arguments[0].toLowerCase();
        var results = [];
        var metas = document.querySelectorAll('meta[name], meta[property]');
        for (var i = 0; i < metas.length; i++) {
            var content = metas[i].getAttribute('content') || '';
            if (content.toLowerCase().indexOf(kw) !== -1) {
                results.push({
                    tag: 'meta ' + (metas[i].getAttribute('name') || metas[i].getAttribute('property')),
                    value: content.substring(0, 300)
                });
            }
        }
        return JSON.stringify(results);
        """
        try:
            raw = state._browser.get_current_tab().run_js(js)
            meta_matches = _json.loads(raw)
            for m in meta_matches:
                results.append({"source": f"[Page] {m['tag']}", "field": "", "value": m["value"]})
        except Exception:
            pass

        if kw_lower in html.lower():
            pos = html.lower().index(kw_lower)
            start = max(0, pos - 100)
            end = min(len(html), pos + len(keyword) + 100)
            snippet = html[start:end].replace('\n', ' ').replace('\r', '')[:250]
            tag = "HTML source"
            if '__INITIAL_STATE__' in html[max(0, pos-200):pos]:
                tag = "HTML source (inside __INITIAL_STATE__)"
            elif '<meta' in html[max(0, pos-200):pos]:
                tag = "HTML source (meta tag)"
            results.append({"source": f"[Page] {tag}", "field": "tab.html", "value": f"...{snippet}..."})

    if not results:
        return f"{state.prefix(tab_num)}\nNo matches found for '{keyword}' in any data source."

    lines = [state.prefix(tab_num), f'Context for "{keyword}":', ""]
    for i, r in enumerate(results):
        lines.append(f"--- Match #{i+1} ---")
        lines.append(f"Source: {r['source']}")
        if r.get("field"):
            lines.append(f"Field:  {r['field']}")
        lines.append(f"Value:  {r['value']}")
        lines.append("")

    return "\n".join(lines)


@state.mcp.tool()
def scout_export(index: int, format: str = "both", tab: int = 0) -> str:
    """Export a captured API data source.

    Args:
        index: API endpoint ID (from scout_apis output).
        format: "raw" | "compact" | "both" (default "both").
        tab: Tab number (0 = current active tab).

    Returns:
        Export result with saved file path and/or field document.
    """
    tab_num, monitor, _dom = state.resolve_tab(tab)
    if not monitor:
        return "No data to export. Call scout_open() first."

    exporter = state.get_exporter()
    record = monitor.get_record(index)
    if not record:
        return f"{state.prefix(tab_num)}\nAPI #{index} not found."

    result = exporter.export(record, format)
    return f"{state.prefix(tab_num)}\n{result}"


@state.mcp.tool()
def scout_export_all(format: str = "both", tab: int = 0) -> str:
    """Export all captured API data sources at once.

    Iterates through every captured API endpoint and exports each one
    to the response/ directory. Much faster than calling scout_export()
    multiple times when you have many endpoints.

    Args:
        format: "raw" | "compact" | "both" (default "both").
        tab: Tab number (0 = current active tab).

    Returns:
        Summary of how many APIs were exported and the output directory.
    """
    tab_num, monitor, _dom = state.resolve_tab(tab)
    if not monitor:
        return "No data to export. Call scout_open() first."

    exporter = state.get_exporter()
    records = monitor.api_records + monitor.embedded_records
    if not records:
        return f"{state.prefix(tab_num)}\nNo APIs captured yet."

    results = []
    for record in records:
        try:
            exporter.export(record, format)
            results.append(f"  [{record['id']}] {record['method']} {record['path']}  -> exported")
        except Exception as e:
            results.append(f"  [{record['id']}] {record['method']} {record['path']}  -> FAILED: {e}")

    lines = [
        state.prefix(tab_num),
        f"Batch export complete: {len(results)} APIs exported.",
        f"Output directory: {exporter.response_dir}/",
        "",
    ]
    lines.extend(results)
    return "\n".join(lines)


@state.mcp.tool()
def scout_peek(
    url: str, path_contains: str | None = None, method: str | None = None
) -> str:
    """One-shot API discovery: open a URL, capture and inspect matching API.

    Opens the URL in a new tab, captures network requests, and returns
    the first JSON API matching the path filter. Does not retain page state
    — use scout_open() for persistent sessions.

    Args:
        url: Target page URL.
        path_contains: Optional API path filter (e.g. "/search/notes").
        method: Optional HTTP method filter ("GET" or "POST").

    Returns:
        API inspect details and field document, or list of captured APIs if no match.
    """
    if not state._browser:
        state._browser = BrowserSession()

    try:
        state._browser.open(url)
        time.sleep(3)

        tab_num = state._browser.tab_num()
        monitor = NetworkMonitor(state._browser.get_current_tab())
        monitor.start()
        state._monitors[tab_num] = monitor
        monitor.step(timeout=5.0)

        if not monitor.api_records:
            return "No JSON API requests were captured on this page."

        if path_contains:
            matches = [r for r in monitor.api_records if path_contains.lower() in r["path"].lower()]
            if method:
                matches = [r for r in matches if r["method"].upper() == method.upper()]
        else:
            matches = monitor.api_records[:1]

        if not matches:
            lines = [f"No API matching path='{path_contains}'"
                     + (f" method={method}" if method else "") + ".",
                     f"Captured {len(monitor.api_records)} APIs:",
                     "", monitor.list_apis()]
            return f"{state.prefix(tab_num)}\n" + "\n".join(lines)

        target = matches[0]
        exporter = Exporter()
        inspect_text = monitor.get_api(target["id"])
        compact_text = exporter.compact(target)
        return f"{state.prefix(tab_num)}\n=== Matched API #{target['id']} ===\n{inspect_text}\n\n=== Field Document ===\n{compact_text}"

    except Exception as e:
        return f"scout_peek failed: {e}"
