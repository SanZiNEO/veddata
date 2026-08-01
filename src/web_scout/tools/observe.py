"""Observe tools — read current page state."""

import asyncio
import json
import os
import time

from web_scout import state


@state.mcp.tool()
async def scout_fetch(max_length: int = 5000, start_index: int = 0, tab: str = "") -> str:
    """获取页面全文，辅助定位数据关键词。当需要从页面文本中选取关键词来反查数据时使用。

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
        return "Error: no browser session."

    tab_id = state._browser.resolve_tab_id(tab) or state._browser.current_tab_id()
    page = await state._browser.get_page_by_id(tab_id)
    if page is None:
        return f"Tab {tab_id[:8]} not found."

    save_dir = os.environ.get('RESPONSE_DIR', './response')
    cache_path = f"{save_dir}/fetch_{tab_id[:8]}.json"
    os.makedirs(save_dir, exist_ok=True)

    if not os.path.exists(cache_path):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1.5)

        text = await page.evaluate("document.body.innerText || ''")
        if not isinstance(text, str):
            text = ""

        raw_links = await page.evaluate(
            "[...document.querySelectorAll('a[href]')].map(a => ({name: (a.innerText||'').trim().slice(0,60), url: a.href}))"
        ) or []
        links = []
        for item in raw_links:
            name = (item.get("name") or "").strip()
            url = item.get("url") or ""
            if not name or url.startswith("javascript:"):
                continue
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

    try:
        title = await page.title() or ""
    except Exception:
        title = ""

    lines = [
        state.prefix(tab_id),
        f"({len(text)} chars total)",
        f"Title: {title}",
        "",
        f"=== Text ({start_index} ~ {start_index + len(chunk)}) ===",
        chunk,
    ]
    if segment_links:
        lines.append("\n=== Links in this segment ===")
        for l in segment_links:
            lines.append(f"[link] {l['name']} -> {l['url']}")
    if len(chunk) == max_length and len(text) > start_index + max_length:
        lines.append("\n... (truncated)")
    return "\n".join(lines)


@state.mcp.tool()
async def scout_screenshot(name: str = "screenshot", full_page: bool = True) -> str:
    """Take a screenshot of the current page.

    Args:
        name: Base filename (without extension). Default "screenshot".
        full_page: True = entire page, False = visible viewport.

    Returns:
        File path of the saved screenshot with tab context.
    """
    if not state._browser:
        return "Error: no browser session."

    try:
        page = await state._browser.get_current_page()
        if page is None:
            return "Error: no page available."
        save_dir = os.environ.get('RESPONSE_DIR', './response')
        os.makedirs(save_dir, exist_ok=True)
        path = os.path.join(save_dir, f"{name}.png")
        await page.screenshot(path=path, full_page=full_page)
        return f"{state.current_prefix()}\nScreenshot saved: {path}"
    except Exception as e:
        return f"Screenshot failed: {e}"


@state.mcp.tool()
async def scout_dom_tree(depth: int = 4, tab: str = "") -> str:
    """输出当前页面的 DOM 目录树（内存快照，含容器/字段/交互标记）。

    首次调用或页面导航后会自动重新扫描；此后从内存读取，不再调浏览器。

    Args:
        depth: 树的显示深度（默认 4）。
        tab: CDP short ID（空 = 当前激活 tab）。

    Returns:
        格式化 DOM 树。
    """
    tree = await _ensure_tree(tab)
    if tree is None:
        return "Error: no browser session."
    return f"{state.prefix(tree.tab_id)}\n{tree.format(depth)}"


@state.mcp.tool()
async def scout_dom_search(text: str, tab: str = "") -> str:
    """在内存 DOM 树中搜索文本。

    不调浏览器，直接在保存的树结构里查找。返回匹配的节点路径和上下文。

    Args:
        text: 搜索关键字（匹配文本/属性/id，大小写不敏感）。
        tab: CDP short ID（空 = 当前激活 tab）。

    Returns:
        匹配节点路径列表。
    """
    tree = await _ensure_tree(tab)
    if tree is None:
        return "Error: no browser session."
    matches = tree.search(text)
    if not matches:
        return f"{state.prefix(tree.tab_id)}\nNo matches in DOM tree."
    lines = [state.prefix(tree.tab_id), f"DOM matches for '{text}':", ""]
    for path, node in matches[:30]:
        summary = node.text[:60] if node.text else ""
        lines.append(f"  {path}" + (f'  "{summary}"' if summary else ""))
    if len(matches) > 30:
        lines.append(f"  ... and {len(matches) - 30} more")
    return "\n".join(lines)


@state.mcp.tool()
async def scout_dom_locate(path: str, tab: str = "") -> str:
    """通过路径定位一个 DOM 节点。

    path 格式: div.content > div.post-list > article:nth-child(3)
    返回该节点的完整子树。

    Args:
        path: 节点路径（tag[.class][#id][:nth-child(n)]，`>` 分隔）。
        tab: CDP short ID（空 = 当前激活 tab）。

    Returns:
        节点子树。
    """
    tree = await _ensure_tree(tab)
    if tree is None:
        return "Error: no browser session."
    node = tree.locate(path)
    if node is None:
        return f"{state.prefix(tree.tab_id)}\nPath not found: {path}"
    lines = [state.prefix(tree.tab_id), path]
    _walk(node, "", "", 0, 6, lines)
    return "\n".join(lines)


async def _ensure_tree(tab: str = ""):
    """Get (or lazily snapshot) the DOM tree for a tab. Returns None if no browser."""
    if not state._browser:
        return None
    tab_id = state._browser.resolve_tab_id(tab) or state._browser.current_tab_id()
    page = await state._browser.get_page_by_id(tab_id)
    if page is None:
        return None
    tree = state._dom_trees.get(tab_id)
    try:
        page_url = page.url
    except Exception:
        page_url = ""
    if tree is None or tree.page_url != page_url:
        from web_scout.dom import snapshot_tree
        tree = await snapshot_tree(page)
        tree.tab_id = tab_id
        state._dom_trees[tab_id] = tree
    return tree


def _walk(node, prefix, connector, level, depth, lines):
    if level >= depth:
        return
    line = prefix + connector + node.selector
    if node.text:
        line += f'  "{node.text}"'
    lines.append(line)
    child_prefix = prefix + ("    " if connector == "└── " else "│   ")
    for i, child in enumerate(node.children):
        last = (i == len(node.children) - 1)
        c = "└── " if last else "├── "
        _walk(child, child_prefix, c, level + 1, depth, lines)


@state.mcp.tool()
async def scout_cookies(all_domains: bool = False, all_info: bool = False, tab: str = "") -> str:
    """View cookies for the current page.

    Args:
        all_domains: False = current domain only, True = all domains.
        all_info: False = name/value/domain only, True = include path/httpOnly/secure/expires.
        tab: CDP short ID (empty = current active tab).

    Returns:
        Formatted cookie list.
    """
    if not state._browser:
        return "Error: no browser session."

    tab_id = state._browser.resolve_tab_id(tab) or state._browser.current_tab_id()
    page = await state._browser.get_page_by_id(tab_id)
    if page is None:
        return f"Tab {tab_id[:8]} not found."

    try:
        if all_domains:
            cookies = await page.context.cookies()
        else:
            cookies = await page.context.cookies(urls=[page.url])
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


@state.mcp.tool()
async def scout_console(code: str = "", tail: int = 0, filter: str = "", tab: str = "") -> str:
    """操作页面控制台：执行 JS / 查看 log/warn/error 消息。

    code 非空 → 在页面执行 JS，返回执行结果。
    code 为空 → 返回控制台历史消息（log/warn/error，来自官方内置缓冲）。
    tail → 只看最近 N 条；filter → 按文本过滤。

    Args:
        code: 要执行的 JS 代码（空 = 查看历史消息）。
        tail: 只看最近 N 条消息（0 = 全部）。
        filter: 按文本过滤消息。
        tab: CDP short ID（空 = 当前激活 tab）。

    Returns:
        执行结果或消息列表。
    """
    if not state._browser:
        return "Error: no browser session."
    tab_id = state._browser.resolve_tab_id(tab) or state._browser.current_tab_id()
    page = await state._browser.get_page_by_id(tab_id)
    if page is None:
        return f"Tab {tab_id[:8]} not found."

    if code:
        try:
            result = await page.evaluate(code)
            try:
                return json.dumps(result, ensure_ascii=False, default=str)[:3000]
            except Exception:
                return str(result)[:3000]
        except Exception as e:
            return f"Error: {e}"

    msgs = []
    try:
        for m in await page.console_messages():
            msgs.append({"type": m.type, "text": m.text})
    except Exception:
        pass
    try:
        for e in await page.page_errors():
            msgs.append({"type": "error", "text": str(e)})
    except Exception:
        pass

    if filter:
        msgs = [m for m in msgs if filter in m["text"]]
    if tail > 0:
        msgs = msgs[-tail:]
    if not msgs:
        return f"{state.prefix(tab_id)}\n(no console messages)"

    lines = [state.prefix(tab_id), f"Console messages ({len(msgs)}):"]
    for m in msgs:
        lines.append(f"[{m['type']}] {m['text'][:2000]}")
    return "\n".join(lines)
