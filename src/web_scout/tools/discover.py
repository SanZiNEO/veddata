"""Discover tools — API data discovery, inspection, search, and export."""

import json as _json
import time

from web_scout import state
from web_scout.browser import BrowserSession
from web_scout.monitor import NetworkMonitor
from web_scout.export import Exporter


def _parse_indices(index: int, indices: str) -> list[int]:
    """Parse index and indices params into a list of int IDs."""
    if indices:
        return [int(x.strip()) for x in indices.split(",") if x.strip()]
    if index:
        return [index]
    return []


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
def scout_inspect(index: int = 0, detail: str = "preview", tab: int = 0, indices: str = "") -> str:
    """Show full request and response details for one or more APIs.

    Pass comma-separated IDs in `indices` to inspect multiple (e.g. "1,3,5").
    Use `index` for a single API.

    Args:
        index: API endpoint ID (from scout_apis output). Use 0 when using indices.
        detail: "preview" (default) = truncated summary with key headers.
                "full" = complete headers + full field structure tree.
        tab: Tab number (0 = current active tab).
        indices: Comma-separated API IDs (e.g. "1,3,5"). Overrides index.

    Returns:
        Formatted request/response details + compressed field document.
    """
    tab_num, monitor, _dom = state.resolve_tab(tab)
    if not monitor:
        return "No APIs captured. Call scout_open() first."

    monitor.flush()
    ids = _parse_indices(index, indices)
    exporter = state.get_exporter()
    parts = [state.prefix(tab_num)]

    for i, n in enumerate(ids):
        record = monitor.get_record(n)
        if not record:
            parts.append(f"API #{n} not found.")
            continue
        if len(ids) > 1:
            parts.append(f"\n--- API #{n} ---")
        inspect_text = monitor.get_api(n, detail)
        parts.append(inspect_text)
        compact_text = exporter.compact(record)
        if compact_text:
            parts.append("\n=== Field Document ===")
            parts.append(compact_text)

    return "\n".join(parts)


@state.mcp.tool()
def scout_search(keyword: str, tab: int = 0) -> str:
    """Search for data by keyword across ALL captured network data.

    Supports comma-separated keywords for OR search (e.g. "title,author").
    Searches API response bodies, SSR embedded JSON, page HTML source, and DOM text.

    Args:
        keyword: Search term, or comma-separated terms for OR logic.
        tab: Tab number (0 = current active tab).

    Returns:
        Numbered list of matching data sources.
    """
    tab_num, monitor, dom = state.resolve_tab(tab)
    if not monitor:
        return "No data. Call scout_open() first."

    keywords = [k.strip() for k in keyword.split(",") if k.strip()]
    monitor.flush()
    lines = [state.prefix(tab_num), ""]

    # 1. JSON API records — OR across all keywords, deduped by ID
    api_ids = set()
    api_lines = []
    for kw in keywords:
        api_result = monitor.list_apis(keyword=kw)
        if api_result and api_result != "No APIs captured yet.":
            for line in api_result.split("\n"):
                if line.startswith("[") and "]" in line[:6]:
                    try:
                        rid = int(line[1:line.index("]")])
                        if rid not in api_ids:
                            api_ids.add(rid)
                            api_lines.append(line)
                    except ValueError:
                        api_lines.append(line)
                else:
                    api_lines.append(line)
    if api_lines:
        lines.append("=== API Matches ===")
        lines.extend(api_lines)
        lines.append("")

    # 2. Page HTML source
    if state._browser:
        html = state._browser.get_current_tab().html
        matched = [k for k in keywords if k.lower() in html.lower()]
        if matched:
            lines.append(f"=== Page HTML matched === (contains '{', '.join(matched)}' in source)")
            lines.append(f"URL: {state._browser.get_current_tab().url}")
            lines.append("Use scout_context() to see WHERE in the page source.")

    # 3. DOM scan
    if dom:
        for kw in keywords:
            dom_result = dom.scan_by_keyword(kw)
            if dom_result and "No elements" not in dom_result:
                lines.append("")
                lines.append(f"=== DOM Matches ({kw}) ===")
                lines.append(dom_result)

    if len(lines) <= 2:
        return f"{state.prefix(tab_num)}\nNo matches for '{keyword}' in any data source."

    display = keyword if len(keywords) == 1 else f"{len(keywords)} keywords: {', '.join(keywords)}"
    lines.insert(1, f'Search results for {display}:')
    lines.append("")
    lines.append("Use scout_context() to see field paths and values for each match.")
    return "\n".join(lines)


@state.mcp.tool()
def scout_context(keyword: str, tab: int = 0) -> str:
    """Search all data sources for keyword, returning field paths and values.

    Supports comma-separated keywords for OR search (e.g. "title,author").

    Args:
        keyword: Search term, or comma-separated terms for OR logic.
        tab: Tab number (0 = current active tab).

    Returns:
        Detailed field paths and sample values for each match.
    """
    tab_num, monitor, dom = state.resolve_tab(tab)
    if not monitor:
        return "No data. Call scout_open() first."

    keywords = [k.strip() for k in keyword.split(",") if k.strip()]
    monitor.flush()
    results = []

    for kw in keywords:
        results.extend(monitor.find_context(kw))

    # DOM search
    if dom:
        for kw in keywords:
            dom_result = dom.scan_by_keyword(kw)
            if dom_result and "No elements" not in dom_result:
                results.append({"source": f"[DOM] ({kw})", "field": "", "value": dom_result})

    # Page meta + HTML source search
    if state._browser:
        html = state._browser.get_current_tab().html
        for kw in keywords:
            kw_lower = kw.lower()
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
                    results.append({"source": f"[Page] {m['tag']} ({kw})", "field": "", "value": m["value"]})
            except Exception:
                pass

            if kw_lower in html.lower():
                pos = html.lower().index(kw_lower)
                start = max(0, pos - 100)
                end = min(len(html), pos + len(kw) + 100)
                snippet = html[start:end].replace('\n', ' ').replace('\r', '')[:250]
                tag = "HTML source"
                if '__INITIAL_STATE__' in html[max(0, pos-200):pos]:
                    tag = "HTML source (inside __INITIAL_STATE__)"
                elif '<meta' in html[max(0, pos-200):pos]:
                    tag = "HTML source (meta tag)"
                results.append({"source": f"[Page] {tag} ({kw})", "field": "tab.html", "value": f"...{snippet}..."})

    if not results:
        return f"{state.prefix(tab_num)}\nNo matches found for '{keyword}' in any data source."

    display = keyword if len(keywords) == 1 else f"{len(keywords)} keywords: {', '.join(keywords)}"
    lines = [state.prefix(tab_num), f'Context for {display}:', ""]
    for i, r in enumerate(results):
        lines.append(f"--- Match #{i+1} ---")
        lines.append(f"Source: {r['source']}")
        if r.get("field"):
            lines.append(f"Field:  {r['field']}")
        lines.append(f"Value:  {r['value']}")
        lines.append("")

    return "\n".join(lines)


@state.mcp.tool()
def scout_export(index: int = 0, format: str = "both", tab: int = 0, indices: str = "") -> str:
    """Export one or more captured API data sources.

    Pass comma-separated IDs in `indices` for multiple (e.g. "2,4").
    Use `index` for a single API.

    Args:
        index: API endpoint ID (from scout_apis output). Use 0 when using indices.
        format: "raw" | "compact" | "both" (default "both").
        tab: Tab number (0 = current active tab).
        indices: Comma-separated API IDs (e.g. "2,4"). Overrides index.

    Returns:
        Export result with saved file path and/or field document.
    """
    tab_num, monitor, _dom = state.resolve_tab(tab)
    if not monitor:
        return "No data to export. Call scout_open() first."

    ids = _parse_indices(index, indices)
    exporter = state.get_exporter()
    parts = [state.prefix(tab_num)]

    exported = 0
    for n in ids:
        record = monitor.get_record(n)
        if not record:
            parts.append(f"API #{n} not found.")
            continue
        if len(ids) > 1:
            parts.append(f"\n--- API #{n} ---")
        result = exporter.export(record, format)
        parts.append(result)
        exported += 1

    if len(ids) > 1:
        parts.insert(1, f"Batch export: {exported}/{len(ids)} APIs exported.")
    return "\n".join(parts)


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
