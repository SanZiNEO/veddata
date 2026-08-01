"""Discover tools — API data discovery, inspection, search, export, and request."""

import asyncio
import json as _json
import time

from web_scout import state
from web_scout.browser import BrowserSession
from web_scout.network_monitor import NetworkMonitor
from web_scout.export import Exporter
from web_scout.requester import exec_request
from web_scout.watch_engine import WatchEngine


def _parse_indices(index: int, indices: str) -> list[int]:
    if indices:
        return [int(x.strip()) for x in indices.split(",") if x.strip()]
    if index:
        return [index]
    return []


@state.mcp.tool()
def scout_apis(keyword: str | None = None, tab: str = "") -> str:
    """列出已捕获的所有数据。包括网络请求、DOM 内嵌数据、JS 变量等。每条记录标注触发时机，不贴类型标签。

    Args:
        keyword: Optional filter on path or response body.
        tab: CDP short ID (empty = current active tab).

    Returns:
        Numbered list of captured data records.
    """
    if not state._browser:
        return "Error: no browser session."
    tab_id = state._browser.current_tab_id()
    if tab:
        tab_id = state._browser.resolve_tab_id(tab) or tab
    pool = state.get_pool()
    if not pool:
        return "No data captured yet."
    result = pool.list_apis(keyword=keyword, tab_id=tab_id)
    return f"{state.prefix(tab_id)}\n{result}"


@state.mcp.tool()
def scout_inspect(index: int = 0, detail: str = "preview", tab: str = "", indices: str = "") -> str:
    """Show full request and response details for one or more APIs.

    Args:
        index: API ID (from scout_apis output). Use 0 when using indices.
        detail: "preview" or "full".
        tab: CDP short ID (empty = current active tab).
        indices: Comma-separated API IDs (e.g. "2,4"). Overrides index.

    Returns:
        Request/response details per record.
    """
    if not state._browser:
        return "Error: no browser session."
    tab_id = state._browser.current_tab_id()
    if tab:
        tab_id = state._browser.resolve_tab_id(tab) or tab
    pool = state.get_pool()
    if not pool:
        return "No data."

    ids = _parse_indices(index, indices)
    parts = [state.prefix(tab_id)]
    for n in ids:
        record = pool.get_record(n, tab_id)
        if not record:
            parts.append(f"API #{n} not found.")
            continue
        if len(ids) > 1:
            parts.append(f"\n--- API #{n} ---")
        parts.append(pool.inspect(n, detail=detail, tab_id=tab_id))
    if not ids:
        parts.append("Provide index (from scout_apis) or indices.")
    return "\n".join(parts)


@state.mcp.tool()
async def scout_search(keyword: str, tab: str = "") -> str:
    """在已捕获的所有数据中搜索关键词。包括网络请求、DOM 内嵌 JSON、页面渲染文本和 JS 全局变量。

    Supports comma-separated keywords for OR search.

    Args:
        keyword: Search term, or comma-separated terms for OR logic.
        tab: CDP short ID (empty = current active tab).

    Returns:
        Matching data sources.
    """
    if not state._browser:
        return "Error: no browser session."
    tab_id = state._browser.current_tab_id()
    if tab:
        tab_id = state._browser.resolve_tab_id(tab) or tab
    pool = state.get_pool()
    if not pool:
        return "No data."

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

    registry = state._script_registries.get(tab_id)
    if registry:
        script_lines = []
        for kw in keywords:
            for group in registry.search(kw):
                url = group["url"]
                script_lines.append(f"  {url} ── {len(group['matches'])} matches")
                for m in group["matches"][:5]:
                    script_lines.append(f"    行 {m['line']}: {m['text'][:120]}")
        if script_lines:
            lines.append("=== Script Matches ===")
            lines.extend(script_lines)
            lines.append("")

    tree = state._dom_trees.get(tab_id)
    if tree:
        for kw in keywords:
            matches = tree.search(kw)
            if matches:
                lines.append("")
                lines.append(f"=== DOM Matches ({kw}) ===")
                for path, node in matches[:20]:
                    summary = node.text[:60] if node.text else ""
                    lines.append(f"  {path}" + (f'  "{summary}"' if summary else ""))
                if len(matches) > 20:
                    lines.append(f"  ... and {len(matches) - 20} more")

    if len(lines) <= 2:
        return f"{state.prefix(tab_id)}\nNo matches for '{keyword}'."

    display = keyword if len(keywords) == 1 else f"{len(keywords)} keywords: {', '.join(keywords)}"
    lines.insert(1, f'Search results for {display}:')
    return "\n".join(lines)


@state.mcp.tool()
async def scout_context(keyword: str, tab: str = "") -> str:
    """Search all data sources for keyword, returning field paths and values.

    Args:
        keyword: Search term, or comma-separated terms for OR logic.
        tab: CDP short ID (empty = current active tab).

    Returns:
        Detailed field paths and sample values.
    """
    if not state._browser:
        return "Error: no browser session."
    tab_id = state._browser.current_tab_id()
    if tab:
        tab_id = state._browser.resolve_tab_id(tab) or tab
    pool = state.get_pool()
    if not pool:
        return "No data."

    keywords = [k.strip() for k in keyword.split(",") if k.strip()]
    results = []

    for kw in keywords:
        results.extend(pool.find_context(kw, tab_id=tab_id))

    registry = state._script_registries.get(tab_id)
    if registry:
        for kw in keywords:
            for group in registry.search(kw):
                for m in group["matches"][:5]:
                    results.append({
                        "source": f"[源码] {group['url']}:{m['line']}",
                        "field": "",
                        "value": m["text"],
                    })

    tree = state._dom_trees.get(tab_id)
    if tree:
        for kw in keywords:
            matches = tree.search(kw)
            if matches:
                value = "\n".join(f"  {p}" + (f'  "{n.text[:60]}"' if n.text else "") for p, n in matches[:20])
                results.append({"source": f"[DOM] ({kw})", "field": "", "value": value})

    if not results:
        return f"{state.prefix(tab_id)}\nNo matches found."

    display = keyword if len(keywords) == 1 else f"{len(keywords)} keywords: {', '.join(keywords)}"
    lines = [state.prefix(tab_id), f'Context for {display}:', ""]
    for i, r in enumerate(results[:30]):
        lines.append(f"--- Match #{i+1} ---")
        lines.append(f"Source: {r['source']}")
        if r.get("field"):
            lines.append(f"Field:  {r['field']}")
        lines.append(f"Value:  {r['value']}")
        lines.append("")
    if len(results) > 30:
        lines.append(f"... and {len(results) - 30} more")
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
    if not state._browser:
        return "Error: no browser session."
    tab_id = state._browser.current_tab_id()
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
    if not state._browser:
        return "Error: no browser session."
    tab_id = state._browser.current_tab_id()
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
async def scout_peek(url: str, path_contains: str | None = None, method: str | None = None) -> str:
    """快速探测指定 URL 的数据源。打开页面 → 自动捕获 API → 返回字段文档。

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
        pool = NetworkMonitor()
        state.set_pool(pool)

    try:
        await state._browser.open(url)
        await asyncio.sleep(3)

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
async def scout_request(
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
        result = await exec_request(
            record=record,
            override_params=params,
            override_body=body,
            override_headers=headers,
            tab_id=tab_id,
        )
    elif url:
        result = await exec_request(
            record={"url": url, "method": method},
            override_params=params,
            override_body=body,
            override_headers=headers,
            tab_id=tab_id,
        )
    else:
        return "Provide index (replay) or url (manual)."
    return result


# ---- Phase 4: 批量观测 + 脚本分析 ----


async def _get_watch_engine(tab_id: str):
    """Get (or lazily create) the WatchEngine for a tab."""
    engine = state._watches.get(tab_id)
    if engine is not None:
        return engine
    page = await state._browser.get_page_by_id(tab_id)
    if page is None:
        return None
    registry = state._script_registries.get(tab_id)
    cdp = registry._cdp if registry else await page.context.new_cdp_session(page)
    engine = WatchEngine(page, cdp, registry)
    state._watches[tab_id] = engine
    return engine


def _format_watch_report(snapshots: list[dict]) -> str:
    lines = [f"Watch snapshots ({len(snapshots)}):", ""]
    for s in snapshots:
        lines.append(f"--- Watch {s['watch_id']} ---")
        lines.append(f"type: {s['type']}")
        if s["type"] == "request":
            lines.append(f"url: {s['url']}")
            lines.append(f"method: {s['method']}")
            lines.append(f"headers: {_json.dumps(s['headers'], ensure_ascii=False)[:400]}")
        else:
            lines.append(f"url: {s['url']}")
            lines.append(f"line: {s['line']}")
            if s.get("source"):
                lines.append(f"source: {s['source']}")
            lines.append(f"variables: {_json.dumps(s.get('variables', {}), ensure_ascii=False)}")
            for frame in s.get("call_stack", [])[:3]:
                lines.append(f"  at {frame}")
        lines.append("")
    return "\n".join(lines)


@state.mcp.tool()
async def scout_watch(
    observations: list | None = None,
    collect: bool = False,
    timeout: float = 15.0,
    tab: str = "",
) -> str:
    """注册多个观测点（请求+JS），触发后一次返回快照。

    Two-step flow:
      1. scout_watch(observations=[{...}, ...]) — 注册，返回观测点清单。
      2. scout_act(...) — 执行操作触发观测点（自动记录并继续执行）。
      3. scout_watch(collect=True) — 等所有观测点收齐（或超时），返回报告并清理。

    observation 项：
      {"type": "request", "pattern": "/api/*"}          — 匹配 URL 的请求（glob 或 /regex/）
      {"type": "js", "url": "...app.js", "line": 147,
       "variables": ["userid", "secret"]}               — 断点命中时记录变量值

    Args:
        observations: 观测点列表；None 且非 collect 时返回当前快照数。
        collect: True = 等待并收集快照，然后清理观测点。
        timeout: 收集超时秒数（默认 15）。
        tab: CDP short ID（空 = 当前激活 tab）。

    Returns:
        注册清单或观测报告。
    """
    if not state._browser:
        return "Error: no browser session."
    tab_id = state._browser.resolve_tab_id(tab) or state._browser.current_tab_id()

    if observations:
        engine = await _get_watch_engine(tab_id)
        if engine is None:
            return "Error: no page available."
        registered = []
        for i, obs in enumerate(observations):
            watch_id = obs.get("watch_id") or f"w{i + 1}"
            obs_type = obs.get("type", "")
            if obs_type == "request":
                await engine.add_request_watch(obs.get("pattern", "**/*"), watch_id)
                registered.append(f"{watch_id}(REQUEST {obs.get('pattern', '**/*')})")
            elif obs_type == "js":
                await engine.add_js_watch(
                    obs.get("url", ""),
                    int(obs.get("line", 0)),
                    obs.get("variables", []),
                    watch_id,
                )
                registered.append(f"{watch_id}(JS {obs.get('url', '')}:{obs.get('line', 0)})")
            else:
                return f"Unsupported observation type: {obs_type} (use 'request' or 'js')"
        return (f"Registered {len(registered)} watches: {', '.join(registered)}")

    if collect:
        engine = state._watches.get(tab_id)
        if engine is None:
            return "No watches registered."
        snapshots = await engine.wait_for_snapshots(timeout=timeout)
        report = _format_watch_report(snapshots)
        await engine.clear()
        return report

    engine = state._watches.get(tab_id)
    if engine is None:
        return "No watches registered."
    return f"Snapshots so far: {engine.snapshot_count()}, pending: {engine.pending_count()}"


@state.mcp.tool()
async def scout_list_scripts(tab: str = "") -> str:
    """列出页面所有 JS 脚本的 URL、大小和行数。

    用于定位目标脚本后传给 scout_script_source。

    Args:
        tab: CDP short ID（空 = 当前激活 tab）。

    Returns:
        脚本清单。
    """
    if not state._browser:
        return "Error: no browser session."
    tab_id = state._browser.resolve_tab_id(tab) or state._browser.current_tab_id()
    registry = state._script_registries.get(tab_id)
    if registry is None:
        page = await state._browser.get_page_by_id(tab_id)
        if page is None:
            return "Error: no page available."
        from web_scout.scripts import ScriptRegistry
        cdp = await page.context.new_cdp_session(page)
        registry = ScriptRegistry(page, cdp)
        await registry.attach(cdp)
        state._script_registries[tab_id] = registry
    await registry.seed()
    for url in list(registry._scripts):
        await registry.get_source(url)
    return f"{state.prefix(tab_id)}\n{registry.list_scripts()}"


@state.mcp.tool()
async def scout_search_scripts(query: str, tab: str = "") -> str:
    """全局搜索：在所有已加载的 JS 源码中搜索字符串。

    结果按文件分组，显示每个文件的匹配行数。
    支持正则（query 以 / 开头和结尾时）。

    Args:
        query: 搜索字符串，或 /regex/ 形式。
        tab: CDP short ID（空 = 当前激活 tab）。

    Returns:
        按文件分组的匹配行。
    """
    if not state._browser:
        return "Error: no browser session."
    tab_id = state._browser.resolve_tab_id(tab) or state._browser.current_tab_id()
    registry = state._script_registries.get(tab_id)
    if registry is None:
        return "No script registry for this tab."
    await registry.seed()
    for url in list(registry._scripts):
        await registry.get_source(url)

    regex = len(query) > 2 and query.startswith("/") and query.endswith("/")
    pattern = query[1:-1] if regex else query
    groups = registry.search(pattern, regex=regex)
    if not groups:
        return f"{state.prefix(tab_id)}\nNo matches for '{query}'."
    lines = [state.prefix(tab_id), f"Script matches for '{query}':", ""]
    for group in groups:
        lines.append(f"{group['url']} ── {len(group['matches'])} matches")
        for m in group["matches"][:10]:
            lines.append(f"  行 {m['line']}: {m['text'][:150]}")
        if len(group["matches"]) > 10:
            lines.append(f"  ... and {len(group['matches']) - 10} more")
    return "\n".join(lines)


@state.mcp.tool()
async def scout_script_source(
    url: str,
    query: str = "",
    context_lines: int = 3,
    start_line: int = 0,
    line_count: int = 50,
    tab: str = "",
) -> str:
    """局部查看：查看某个脚本源码，支持搜索高亮和上下文。

    url: 脚本 URL（从 scout_list_scripts 或 scout_search_scripts 获取）。
    query: 搜索字符串，匹配行会高亮（>>> 前缀）。
    context_lines: 匹配行前后显示几行上下文。
    start_line / line_count: 翻页查看（大文件分段读）。

    Args:
        url: 脚本 URL。
        query: 可选搜索字符串。
        context_lines: 匹配行上下文行数。
        start_line: 起始行（0 = 从头）。
        line_count: 每次显示行数。
        tab: CDP short ID（空 = 当前激活 tab）。

    Returns:
        源码片段。
    """
    if not state._browser:
        return "Error: no browser session."
    tab_id = state._browser.resolve_tab_id(tab) or state._browser.current_tab_id()
    registry = state._script_registries.get(tab_id)
    if registry is None:
        return "No script registry for this tab."
    source = await registry.get_source(url)
    if source is None:
        return f"Source not found: {url}"

    lines = source.splitlines()
    total = len(lines)

    if query:
        import re as _re
        try:
            pat = _re.compile(query)
        except _re.error:
            pat = _re.compile(_re.escape(query))
        hit_lines = [i for i, l in enumerate(lines) if pat.search(l)]
        if not hit_lines:
            return f"No matches for '{query}' in {url}."
        out = []
        shown = set()
        for i in hit_lines[:10]:
            lo = max(0, i - context_lines)
            hi = min(total, i + context_lines + 1)
            for j in range(lo, hi):
                if j in shown:
                    continue
                shown.add(j)
                marker = ">>>" if j == i else "   "
                out.append(f"{marker} {j + 1:5d} | {lines[j][:200]}")
        return f"{state.prefix(tab_id)}\n{url} ({len(hit_lines)} matches)\n" + "\n".join(out)

    if start_line >= total:
        return f"{state.prefix(tab_id)}\n{url}: start_line {start_line} beyond {total} lines."
    out = []
    more = "" if start_line + line_count >= total else "\n... (truncated)"
    return f"{state.prefix(tab_id)}\n{url}\n" + "\n".join(out) + more


# ---- Phase 5: 值追踪 ----


@state.mcp.tool()
async def scout_trace_value(value: str, tab: str = "") -> str:
    """全局搜索一个值出现在哪些地方。

    搜索范围: JS 源码 → 网络请求 → DOM 内嵌 → 渲染文本 → JS 变量 → WS。
    每条匹配标注位置和上下文，支持直接设观测点。

    Args:
        value: 要追踪的值（如 "userid"）。
        tab: CDP short ID（空 = 当前激活 tab）。

    Returns:
        按来源分组的位置清单。
    """
    if not state._browser:
        return "Error: no browser session."
    tab_id = state._browser.resolve_tab_id(tab) or state._browser.current_tab_id()
    page = await state._browser.get_page_by_id(tab_id)
    if page is None:
        return "Error: no page available."
    pool = state.get_pool()
    registry = state._script_registries.get(tab_id)
    tree = state._dom_trees.get(tab_id)

    groups: list[tuple[str, list[str]]] = []

    # 1. JS 源码
    src_lines: list[str] = []
    if registry:
        await registry.seed()
        for url in list(registry._scripts):
            await registry.get_source(url)
        for group in registry.search(value):
            for m in group["matches"][:10]:
                src_lines.append(f"  源码: {group['url']}:{m['line']} → {m['text'][:150]}")
    if src_lines:
        groups.append(("源码", src_lines))

    # 2. 网络请求 + 3. 内嵌
    net_lines: list[str] = []
    emb_lines: list[str] = []
    if pool:
        for rec in pool.get_by_tab(tab_id):
            if rec.get("method") == "-":
                for field_path, val in pool._deep_search(rec.get("response_body", {}), value.lower(), ""):
                    emb_lines.append(f"  内嵌: {rec['source']} → {field_path} = {val[:120]}")
            else:
                for field_path, val in pool._deep_search(rec.get("response_body", {}), value.lower(), ""):
                    net_lines.append(f"  网络: {rec['method']} {rec['path']} → {field_path} = {val[:120]}")
    if net_lines:
        groups.append(("网络", net_lines[:20]))
    if emb_lines:
        groups.append(("内嵌", emb_lines[:20]))

    # 4. 渲染文本
    try:
        found = await page.evaluate(
            "(v) => (document.body.innerText || '').includes(v)", value
        )
        groups.append(("渲染文本", [f"  渲染文本: {'包含' if found else '不包含'} '{value}'"]))
    except Exception:
        pass

    # 5. window 全局变量
    var_lines: list[str] = []
    try:
        keys = await page.evaluate(
            "Object.keys(window).filter(k => k.startsWith('__')).slice(0, 50)"
        ) or []
        for k in keys:
            try:
                s = await page.evaluate(
                    "(k) => { const v = window[k]; return (typeof v === 'object' && v !== null) "
                    "? JSON.stringify(v) : String(v); }",
                    k,
                )
            except Exception:
                continue
            if value.lower() in (s or "").lower():
                var_lines.append(f"  变量: window.{k} = {str(s)[:200]}")
                if len(var_lines) >= 10:
                    break
    except Exception:
        pass
    if var_lines:
        groups.append(("变量", var_lines))

    # 6. WS 历史
    ws_lines: list[str] = []
    if pool:
        for rec in pool.get_by_tab(tab_id):
            for msg in rec.get("ws_messages", []):
                if value.lower() in msg.get("data", "").lower():
                    ws_lines.append(f"  WS: {rec['source']} → {msg['data'][:150]}")
    if ws_lines:
        groups.append(("WS", ws_lines[:10]))

    if not groups:
        return f"{state.prefix(tab_id)}\nNo trace of '{value}' found."

    lines = [state.prefix(tab_id), f"Trace of '{value}':", ""]
    for name, items in groups:
        lines.append(f"=== {name} ===")
        lines.extend(items)
        lines.append("")
    return "\n".join(lines)
