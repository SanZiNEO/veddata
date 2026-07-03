"""Discover tools — API data discovery, inspection, search, export, and request."""

import json as _json
import time

from web_scout import state
from web_scout.browser import BrowserSession
from web_scout.network_pool import NetworkPool
from web_scout.export import Exporter
from web_scout.requester import exec_request


def _parse_indices(index: int, indices: str) -> list[int]:
    if indices:
        return [int(x.strip()) for x in indices.split(",") if x.strip()]
    if index:
        return [index]
    return []


@state.mcp.tool()
def scout_apis(keyword: str | None = None, tab: str = "") -> str:
    """List all captured API endpoints, optionally filtered by keyword.

    Args:
        keyword: Optional filter — only show APIs whose path or response body
            contains this keyword (case-insensitive).
        tab: CDP short ID (empty = current active tab).

    Returns:
        Numbered list with method, path, count, and field count.
    """
    tab_id = state._browser.current_tab_id() if state._browser else ""
    if tab:
        tab_id = state._browser.resolve_tab_id(tab) or tab
    pool = state.get_pool()
    if not pool:
        return "No APIs captured yet."
    result = pool.list_apis(keyword=keyword, tab_id=tab_id)
    return f"{state.prefix(tab_id)}\n{result}"


@state.mcp.tool()
def scout_inspect(index: int = 0, detail: str = "preview", tab: str = "", indices: str = "") -> str:
    """Show full request and response details for one or more APIs.

    Args:
        index: API ID (from scout_apis output). Use 0 when using indices.
        detail: "preview" (default) or "full".
        tab: CDP short ID (empty = current active tab).
        indices: Comma-separated API IDs (e.g. "1,3,5"). Overrides index.

    Returns:
        Formatted request/response details + field document.
    """
    tab_id = state._browser.current_tab_id() if state._browser else ""
    if tab:
        tab_id = state._browser.resolve_tab_id(tab) or tab
    pool = state.get_pool()
    if not pool:
        return "No APIs captured."

    ids = _parse_indices(index, indices)
    exporter = state.get_exporter()
    parts = [state.prefix(tab_id)]

    for n in ids:
        inspect_text = pool.inspect(n, detail, tab_id=tab_id)
        if "not found" in inspect_text:
            parts.append(inspect_text)
            continue
        if len(ids) > 1:
            parts.append(f"\n--- API #{n} ---")
        parts.append(inspect_text)
        record = pool.get_record(n, tab_id)
        if record:
            compact_text = exporter.compact(record)
            if compact_text:
                parts.append(f"\n=== Field Document ===\n{compact_text}")
    return "\n".join(parts)


@state.mcp.tool()
def scout_search(keyword: str, tab: str = "") -> str:
    """Search for data by keyword across ALL captured network data.

    Supports comma-separated keywords for OR search.

    Args:
        keyword: Search term, or comma-separated terms for OR logic.
        tab: CDP short ID (empty = current active tab).

    Returns:
        Matching data sources.
    """
    tab_id = state._browser.current_tab_id() if state._browser else ""
    if tab:
        tab_id = state._browser.resolve_tab_id(tab) or tab
    pool = state.get_pool()
    if not pool:
        return "No data. Call scout_open() first."

    keywords = [k.strip() for k in keyword.split(",") if k.strip()]
    lines = [state.prefix(tab_id), ""]

    api_lines = []
    for kw in keywords:
        result = pool.list_apis(keyword=kw, tab_id=tab_id)
        if result and result != "No APIs captured yet.":
            if result not in api_lines:
                api_lines.append(result)
    if api_lines:
        lines.append("=== API Matches ===")
        lines.extend(api_lines)
        lines.append("")

    dom = state._dom_scanners.get(tab_id)
    if dom:
        for kw in keywords:
            dom_result = dom.scan_by_keyword(kw)
            if dom_result and "No elements" not in dom_result:
                lines.append("")
                lines.append(f"=== DOM Matches ({kw}) ===")
                lines.append(dom_result)

    if len(lines) <= 2:
        return f"{state.prefix(tab_id)}\nNo matches for '{keyword}'."

    display = keyword if len(keywords) == 1 else f"{len(keywords)} keywords: {', '.join(keywords)}"
    lines.insert(1, f'Search results for {display}:')
    lines.append("\nUse scout_context() to see field paths and values.")
    return "\n".join(lines)


@state.mcp.tool()
def scout_context(keyword: str, tab: str = "") -> str:
    """Search all data sources for keyword, returning field paths and values.

    Args:
        keyword: Search term, or comma-separated terms for OR logic.
        tab: CDP short ID (empty = current active tab).

    Returns:
        Detailed field paths and sample values.
    """
    tab_id = state._browser.current_tab_id() if state._browser else ""
    if tab:
        tab_id = state._browser.resolve_tab_id(tab) or tab
    pool = state.get_pool()
    if not pool:
        return "No data."

    keywords = [k.strip() for k in keyword.split(",") if k.strip()]
    results = []

    for kw in keywords:
        results.extend(pool.find_context(kw, tab_id=tab_id))

    dom = state._dom_scanners.get(tab_id)
    if dom:
        for kw in keywords:
            dom_result = dom.scan_by_keyword(kw)
            if dom_result and "No elements" not in dom_result:
                results.append({"source": f"[DOM] ({kw})", "field": "", "value": dom_result})

    if not results:
        return f"{state.prefix(tab_id)}\nNo matches found."

    display = keyword if len(keywords) == 1 else f"{len(keywords)} keywords: {', '.join(keywords)}"
    lines = [state.prefix(tab_id), f'Context for {display}:', ""]
    for i, r in enumerate(results):
        lines.append(f"--- Match #{i+1} ---")
        lines.append(f"Source: {r['source']}")
        if r.get("field"):
            lines.append(f"Field:  {r['field']}")
        lines.append(f"Value:  {r['value']}")
        lines.append("")
    return "\n".join(lines)


@state.mcp.tool()
def scout_export(index: int = 0, format: str = "both", tab: str = "", indices: str = "", output_dir: str | None = None) -> str:
    """Export one or more captured API data sources.

    Args:
        index: API ID (from scout_apis output). Use 0 when using indices.
        format: "raw" | "compact" | "both" (default "both").
        tab: CDP short ID (empty = current active tab).
        indices: Comma-separated API IDs (e.g. "2,4"). Overrides index.
        output_dir: Override save directory.

    Returns:
        Export result with saved file path and/or field document.
    """
    tab_id = state._browser.current_tab_id() if state._browser else ""
    if tab:
        tab_id = state._browser.resolve_tab_id(tab) or tab
    pool = state.get_pool()
    if not pool:
        return "No data to export."

    ids = _parse_indices(index, indices)
    exporter = state.get_exporter(output_dir)
    parts = [state.prefix(tab_id)]
    exported = 0
    for n in ids:
        record = pool.get_record(n, tab_id)
        if not record:
            parts.append(f"API #{n} not found.")
            continue
        if len(ids) > 1:
            parts.append(f"\n--- API #{n} ---")
        parts.append(exporter.export(record, format, output_dir))
        exported += 1
    if len(ids) > 1:
        parts.insert(1, f"Batch export: {exported}/{len(ids)}.")
    return "\n".join(parts)


@state.mcp.tool()
def scout_export_all(format: str = "both", tab: str = "", output_dir: str | None = None) -> str:
    """Export all captured API data sources at once.

    Args:
        format: "raw" | "compact" | "both" (default "both").
        tab: CDP short ID (empty = current active tab).
        output_dir: Override save directory.

    Returns:
        Summary of exported APIs.
    """
    tab_id = state._browser.current_tab_id() if state._browser else ""
    if tab:
        tab_id = state._browser.resolve_tab_id(tab) or tab
    pool = state.get_pool()
    if not pool:
        return "No data to export."

    exporter = state.get_exporter(output_dir)
    records = pool.get_by_tab(tab_id)
    if not records:
        return f"{state.prefix(tab_id)}\nNo APIs captured yet."

    results = []
    for record in records:
        try:
            exporter.export(record, format, output_dir)
            results.append(f"  [{record['id']}] {record['method']} {record['path']}  -> exported")
        except Exception as e:
            results.append(f"  [{record['id']}] {record['method']} {record['path']}  -> FAILED: {e}")

    save_dir = output_dir or exporter.response_dir
    lines = [
        state.prefix(tab_id),
        f"Batch export complete: {len(results)} APIs.",
        f"Output directory: {save_dir}/",
        "",
    ]
    lines.extend(results)
    return "\n".join(lines)


@state.mcp.tool()
def scout_peek(url: str, path_contains: str | None = None, method: str | None = None) -> str:
    """One-shot API discovery: open a URL, capture and inspect matching API.

    Args:
        url: Target page URL.
        path_contains: Optional API path filter (e.g. "/search/notes").
        method: Optional HTTP method filter ("GET" or "POST").

    Returns:
        API inspect details and field document, or list of captured APIs.
    """
    if not state._browser:
        state._browser = BrowserSession()

    pool = state.get_pool()
    if not pool:
        pool = NetworkPool()
        state.set_pool(pool)

    tab = state._browser.get_current_tab()
    pool.start_tab(tab)

    try:
        state._browser.open(url)
        time.sleep(3)
        pool.step(timeout=5.0, tab=tab)

        tab_id = state._browser.current_tab_id()
        records = pool.get_by_tab(tab_id)

        if not records:
            return "No JSON API requests were captured on this page."

        if path_contains:
            matches = [r for r in records if path_contains.lower() in r["path"].lower()]
            if method:
                matches = [r for r in matches if r["method"].upper() == method.upper()]
        else:
            matches = records[:1]

        if not matches:
            lines = [f"No API matching path='{path_contains}'"
                     + (f" method={method}" if method else "") + ".",
                     f"Captured {len(records)} APIs:",
                     "", pool.list_apis(tab_id=tab_id)]
            return f"{state.prefix(tab_id)}\n" + "\n".join(lines)

        target = matches[0]
        exporter = Exporter()
        inspect_text = pool.inspect(target["id"], tab_id=tab_id)
        compact_text = exporter.compact(target)
        return f"{state.prefix(tab_id)}\n=== Matched API #{target['id']} ===\n{inspect_text}\n\n=== Field Document ===\n{compact_text}"

    except Exception as e:
        return f"scout_peek failed: {e}"


@state.mcp.tool()
def scout_request(
    index: int = 0,
    url: str = "",
    method: str = "GET",
    params: str = "",
    body: str = "",
    headers: str = "",
    tab: str = "",
) -> str:
    """Send a test HTTP request — replay from captured API or fully custom.

    Two modes:
    1. Replay: index=3, params='{"page":2}' — uses API #3's URL/method/headers.
    2. Manual: url="...", method="POST", body="..." — fully custom.

    Cookies are auto-synced from the current browser tab.

    Args:
        index: API record number to replay (0 = manual mode).
        url: Request URL (manual mode).
        method: HTTP method (default "GET").
        params: JSON string of query parameters.
        body: JSON string of request body.
        headers: JSON string of extra headers.
        tab: CDP short ID for cookie sync (empty = current active tab).

    Returns:
        Formatted response with status, time, headers, and body.
    """
    tab_id = state._browser.current_tab_id() if state._browser else ""
    if tab:
        tab_id = state._browser.resolve_tab_id(tab) or tab

    if index:
        pool = state.get_pool()
        record = pool.get_record(index, tab_id) if pool else None
        if not record:
            return f"API #{index} not found."
        result = exec_request(
            record=record,
            override_params=params,
            override_body=body,
            override_headers=headers,
            tab_id=tab_id,
        )
    elif url:
        result = exec_request(
            record={"url": url, "method": method},
            override_params=params,
            override_body=body,
            override_headers=headers,
            tab_id=tab_id,
        )
    else:
        return "Provide index (replay) or url (manual)."
    return result
