"""Scan tools — comprehensive page data source discovery."""

import asyncio
import json as _json

from veddata import limits, state
from veddata.browser import BrowserSession
from veddata.network_monitor import NetworkMonitor
from veddata.dom import snapshot_tree


@state.mcp.tool()
async def ved_scan(
    mode: str = "all",
    keyword: str | None = None,
    url: str | None = None,
    offset: int = 0,
    limit: int = limits.LIST_LIMIT,
) -> str:
    """Comprehensive page data source scanner.

    MODE "all" — full page scan (default):
      1. Network APIs — requests captured by the event listener
      2. DOM Structure — snapshot tree with repeated-container marks
      3. Embedded JSON — script-tag / window-global data records

    MODE "dom" — keyword-targeted DOM scan:
      Searches the in-memory DOM tree for the keyword.

    Args:
        mode: "all" for full scan, "dom" for keyword-targeted DOM scan.
        keyword: For mode "dom" — search keyword.
        url: For mode "dom" — optional URL to open before scanning.
        offset: For mode "dom" — 从第几处匹配开始（默认 0）。
        limit: For mode "dom" — 本次返回条数（默认 30）。

    Returns:
        Data source summary for mode "all", or match list for mode "dom"。
        各段都有上限，完整清单用 ved_apis / ved_dom_tree 取。
    """
    if mode == "dom" and url:
        return await _scan_dom_with_url(url, keyword or "", offset, limit)
    elif mode == "dom":
        return await _scan_dom_keyword(keyword or "", offset, limit)
    else:
        return await _scan_all()


async def _scan_all() -> str:
    if not state._browser:
        return "Error: no browser session."
    tab_id = state._browser.current_tab_id()
    pool = state.get_pool()
    if pool:
        pool.reset_trigger()

    await asyncio.sleep(3)
    records = pool.get_by_tab(tab_id) if pool else []
    total_api = len(records)

    page = await state._browser.get_current_page()
    if page is None:
        return "Error: no page available."

    tree = await snapshot_tree(page)
    tree.tab_id = tab_id
    state._dom_trees[tab_id] = tree

    parts = [state.prefix(tab_id), ""]

    parts.append("=== Network APIs ===")
    if total_api > 0:
        api_list = pool.list_apis(tab_id=tab_id) if pool else ""
        lines = api_list.split("\n") if api_list else []
        parts.append(f"{total_api} total:")
        parts.extend(lines[:8])
        if len(lines) > 8:
            parts.append(f"... and {len(lines) - 8} more")
    else:
        parts.append("0 — data may be embedded in HTML/DOM.")
    parts.append("")

    parts.append("=== DOM Structure ===")
    tree_lines = tree.format(3).split("\n")
    parts.extend(tree_lines[:60])
    if len(tree_lines) > 60:
        parts.append(f"... ({len(tree_lines) - 60} more lines, truncated)")
    parts.append("")

    # 重复容器统计
    repeated = []
    for node in tree.find_tag("div"):
        if node.collapsed and node.collapsed_count >= 3:
            repeated.append(node)
    if repeated:
        parts.append(f"=== Repeated Containers ({len(repeated)}) ===")
        for node in repeated[:10]:
            parts.append(f"  {node.selector} [x{node.collapsed_count + 1}]")
        parts.append("")

    embedded = [r for r in records if r.get("method") == "-"]
    parts.append(f"=== Embedded Data ({len(embedded)}) ===")
    for r in embedded[:8]:
        parts.append(f"  {r['source']}  → {r['field_count']} fields")
    if len(embedded) > 8:
        parts.append(f"  ... and {len(embedded) - 8} more")
    parts.append("")
    parts.append("(以上各段都有上限；完整清单：ved_apis / ved_dom_tree，导出用 ved_export)")
    parts.append("---")
    return limits.truncate_text("\n".join(parts))


async def _scan_dom_keyword(keyword: str, offset: int = 0, limit: int = limits.LIST_LIMIT) -> str:
    if not state._browser:
        return "Error: no browser session."
    if not keyword.strip():
        return "Keyword cannot be empty."
    tab_id = state._browser.current_tab_id()
    page = await state._browser.get_current_page()
    if page is None:
        return "Error: no page available."
    tree = state._dom_trees.get(tab_id)
    try:
        page_url = page.url
    except Exception:
        page_url = ""
    if tree is None or tree.page_url != page_url:
        tree = await snapshot_tree(page)
        tree.tab_id = tab_id
        state._dom_trees[tab_id] = tree
    matches = tree.search(keyword)
    if not matches:
        return f"{state.current_prefix()}\nNo elements found for '{keyword}'."
    page, footer = limits.paginate(matches, offset, limit, unit="处匹配")
    lines = [state.current_prefix(), f"DOM matches for '{keyword}':", ""]
    for path, node in page:
        summary = node.text[:60] if node.text else ""
        lines.append(f"  {path}" + (f'  "{summary}"' if summary else ""))
    lines.append(footer)
    return limits.truncate_text("\n".join(lines))


async def _scan_dom_with_url(url: str, keyword: str, offset: int = 0, limit: int = limits.LIST_LIMIT) -> str:
    if not state._browser:
        state._browser = BrowserSession()
    pool = state.get_pool()
    if not pool:
        pool = NetworkMonitor()
        state.set_pool(pool)
    try:
        await state._browser.open(url)
        await asyncio.sleep(2)
        page = await state._browser.get_current_page()
        if page is None:
            return "Error: no page available."
        tree = await snapshot_tree(page)
        tab_id = state._browser.current_tab_id()
        tree.tab_id = tab_id
        state._dom_trees[tab_id] = tree
        matches = tree.search(keyword)
        if not matches:
            return f"{state.current_prefix()}\nNo elements found for '{keyword}'."
        page, footer = limits.paginate(matches, offset, limit, unit="处匹配")
        lines = [state.current_prefix(), f"DOM matches for '{keyword}':", ""]
        for path, node in page:
            summary = node.text[:60] if node.text else ""
            lines.append(f"  {path}" + (f'  "{summary}"' if summary else ""))
        lines.append(footer)
        return limits.truncate_text("\n".join(lines))
    except Exception as e:
        return f"ved_scan failed: {e}"
