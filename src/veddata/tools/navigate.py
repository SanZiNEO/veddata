"""Navigate tools — browser lifecycle, tab management, navigation."""

import asyncio

from veddata import limits, state
from veddata.browser import BrowserSession
from veddata.network_monitor import NetworkMonitor
from veddata.dom import snapshot_tree


@state.mcp.tool()
async def ved_open() -> str:
    """启动数据发现会话。打开浏览器以开始捕获页面数据源。浏览网页是前置步骤，不是终点。

    Launches a Playwright Chromium session (persistent context) and clears
    old state.  Does NOT navigate — use ved_goto() for that.

    Returns:
        Browser session status.
    """
    # 清理旧会话
    if state._browser:
        try:
            await state._browser.close()
        except Exception:
            pass
        state._browser = None
        state.set_pool(None)
        state._dom_trees.clear()

    state._browser = BrowserSession()
    pool = state.get_pool()
    if not pool:
        state.set_pool(NetworkMonitor())

    # 确保会话就绪：复用空白页；已有内容页则直接用，不新建空白页（避免累积 about:blank）
    browser = state._browser
    context = await browser._ensure_browser()
    blank = None
    for p in context.pages:
        if p.url in ("about:blank", "", "chrome://newtab/"):
            blank = p
            break
    if blank is not None:
        await browser._register_tab(blank)
    elif not context.pages:
        blank = await context.new_page()
        await browser._register_tab(blank)
    else:
        # 已有内容页：注册全部未注册页，第一个设为当前
        for p in context.pages:
            if id(p) not in browser._page_to_id:
                await browser._register_tab(p, set_current=False)
        if browser.current_tab_id() not in browser._pages:
            first = context.pages[0]
            tid = browser._page_to_id.get(id(first))
            if tid:
                browser._current_tab = tid

    return "Browser ready."


def _summarize_body(body, max_keys: int = 6) -> str:
    """顶层键摘要：{key: type, ...}"""
    if isinstance(body, dict):
        parts = []
        for k, v in list(body.items())[:max_keys]:
            t = type(v).__name__
            if isinstance(v, list):
                t = f"[{len(v)}]"
            elif isinstance(v, dict):
                t = "{...}"
            parts.append(f"{k}: {t}")
        return "{" + ", ".join(parts) + "}"
    if isinstance(body, list):
        return f"[{len(body)} items]"
    return str(body)[:80]


def _format_data_line(rec: dict) -> list[str]:
    """一条 Captured Data 记录的三行描述（不带类型标签）。"""
    if rec.get("method") == "-" and rec.get("ws_messages") is not None:
        return [
            f"[{rec['id']}] - {rec['source']}",
            f"    触发: {rec.get('trigger', '?')}",
            "    状态: 已连接，等待消息",
        ]
    if rec.get("method") == "-":
        body = rec.get("response_body", {})
        if isinstance(body, dict) and "sample" in body:
            content = f"{body.get('type', '?')} 变量，样本: {str(body.get('sample', ''))[:60]}"
        else:
            content = _summarize_body(body)
        return [
            f"[{rec['id']}] - {rec['source']}",
            f"    触发: {rec.get('trigger', '?')}",
            f"    内容: {content} → {rec['field_count']} fields",
        ]
    line = f"[{rec['id']}] {rec['method']} {rec['path']}"
    params = rec.get("request_params") or {}
    if params:
        qs = "&".join(f"{k}={v}" for k, v in list(params.items())[:4])
        line += f" → ?{qs[:60]}"
    return [
        line,
        f"    触发: {rec.get('trigger', '?')}",
        f"    响应: {_summarize_body(rec.get('response_body', {}))} → {rec['field_count']} fields",
    ]


def _format_actions(tree) -> list[str]:
    """从树快照收集交互节点，格式：类型  选择器 文本/占位符"""
    lines = []
    for tag in ("input", "button", "a", "select"):
        for node in tree.find_tag(tag):
            if tag == "a" and "href" not in node.attrs:
                continue
            label = node.text or node.attrs.get("placeholder") or node.attrs.get("aria-label") or ""
            if not label and tag in ("input", "select"):
                continue
            name = {"input": "输入框", "button": "按钮", "a": "链接", "select": "选择框"}[tag]
            lines.append(f"{name}    {node.selector}  {label[:40]}")
            if len(lines) >= 15:
                return lines
    return lines


@state.mcp.tool()
async def ved_goto(url: str, new_tab: bool = False, depth: int = limits.TREE_DEPTH, limit: int = 10) -> str:
    """导航到目标页面，自动发现所有数据来源。返回 DOM 结构、网络请求、内嵌数据清单。

    Starts network monitoring BEFORE navigating (event-driven attach happens
    at tab registration, which precedes goto).

    Use new_tab=True to open in a new tab while keeping the current page.

    Args:
        url: Target URL to navigate to.
        new_tab: True = create new tab; False = navigate current tab.
        depth: DOM 树深度（默认 2，够看清结构；要细看传 4-8）。
        limit: 捕获清单预览条数（默认 10；完整清单用 ved_apis 分页取）。

    Returns:
        DOM tree（按 depth 限深）+ captured data preview + actions。完整数据留在服务端，随时再取。
    """
    if not state._browser:
        return "Error: no browser session."

    pool = state.get_pool()
    if not pool:
        pool = NetworkMonitor()
        state.set_pool(pool)

    browser = state._browser
    if new_tab:
        context = await browser._ensure_browser()
        page = await context.new_page()
        await browser._register_tab(page)
    else:
        page = await browser.get_current_page()
        if page is None:
            return "Error: no page available."

    tab_id = browser.current_tab_id()
    pool.reset_trigger()

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        return f"Failed to navigate: {e}"

    try:
        await page.wait_for_load_state("domcontentloaded")
    except Exception:
        pass
    await asyncio.sleep(2)

    try:
        await pool.scan_embedded(page)
    except Exception:
        pass

    try:
        title = await page.title() or ""
    except Exception:
        title = ""

    tree = await snapshot_tree(page)
    tree.tab_id = tab_id
    state._dom_trees[tab_id] = tree

    records = pool.get_by_tab(tab_id)
    tree_depth = limits.clamp(depth, low=1, high=8, default=limits.TREE_DEPTH)
    preview = limits.clamp(limit, low=1, high=100, default=10)

    parts = [
        state.prefix(tab_id),
        f"Title: {title}",
        "",
        f"=== DOM Tree (depth={tree_depth}) ===",
        tree.format(tree_depth),
        "",
        f"=== Captured Data ({len(records)} items) ===",
    ]
    for rec in records[:preview]:
        parts.extend(_format_data_line(rec))
    if len(records) > preview:
        parts.append(
            limits.page_footer(
                shown_from=1, shown_to=preview, total=len(records),
                param="offset", next_value=preview, unit="条",
            )
            + "  完整清单：ved_apis"
        )
    parts.append("")
    parts.append("=== Actions ===")
    actions = _format_actions(tree)
    if actions:
        parts.extend(actions[:12])
        if len(actions) > 12:
            parts.append(f"…(显示 12 / 共 {len(actions)} 个可交互元素)")
    else:
        parts.append("(no interactive elements found)")
    return limits.truncate_text(
        "\n".join(parts),
        hint="想更深/更多：depth= 调树深度、limit= 调清单条数；逐项细看用 ved_dom_tree / ved_apis / ved_scan",
    )


@state.mcp.tool()
async def ved_close() -> str:
    """Close the browser and clear all captured data.

    Closes the Playwright context and resets all state.

    Returns:
        Status message.
    """
    if state._browser:
        try:
            await state._browser.close()
        except Exception:
            pass
        state._browser = None
    state.set_pool(None)
    state._dom_trees.clear()
    state._script_registries.clear()
    state._watches.clear()
    state._exporter = None
    return "Browser closed. All data cleared."


@state.mcp.tool()
async def ved_tabs() -> str:
    """List all open browser tabs with CDP short IDs.

    Returns:
        Tab list with short IDs and current marker.
    """
    if not state._browser:
        return "No browser session."
    return await state._browser.list_tabs()


@state.mcp.tool()
async def ved_tab_switch(tab: str) -> str:
    """Switch the active tab by CDP short ID (from ved_tabs output).

    After switching, ved_goto() targets the new tab.

    Args:
        tab: CDP short ID (first 8 chars, from ved_tabs output).

    Returns:
        Status with the new tab's URL.
    """
    if not state._browser:
        return "No browser session."

    result = await state._browser.switch_tab(tab)
    if "not found" in result:
        return result
    tid = state._browser.current_tab_id()
    return f"{result}\n{state.prefix(tid)}"


@state.mcp.tool()
async def ved_tab_close(tab: str = "") -> str:
    """Close browser tab(s) by CDP short ID and prune their API records.

    Supports comma-separated IDs for batch close (e.g. "C724404D,5FD84E84").
    Empty = close current tab.

    Args:
        tab: CDP short ID(s), comma-separated. Empty = current tab.

    Returns:
        Status message.
    """
    if not state._browser:
        return "No browser session."

    tab_ids_to_close = [t.strip() for t in tab.split(",") if t.strip()] if tab else [state._browser.current_tab_id()]
    pool = state.get_pool()
    results = []

    for short_id in tab_ids_to_close:
        tid = state._browser.resolve_tab_id(short_id) or short_id
        result = await state._browser.close_tab(short_id)
        results.append(f"{result}")
        if pool:
            pool.prune(tid)
        state._dom_trees.pop(tid, None)
        state._script_registries.pop(tid, None)
        state._watches.pop(tid, None)

    return "\n".join(results) if len(results) > 1 else results[0]
