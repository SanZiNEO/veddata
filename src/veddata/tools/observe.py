"""Observe tools — read current page state."""

import asyncio
import json
import os
import time
from pathlib import Path

from veddata import limits, naming, observation, paths, state

# ved_fetch 的页面文本缓存：tab id 每次启动浏览器都是新的，不清就会只增不减
_CACHE_KEEP = 32


def _prune_cache(cache_dir: Path) -> None:
    """缓存目录里只保留最近 `_CACHE_KEEP` 个 fetch 缓存。"""
    try:
        files = sorted(
            cache_dir.glob("fetch_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    for stale in files[_CACHE_KEEP:]:
        try:
            stale.unlink()
        except OSError:
            pass


@state.mcp.tool()
@observation.guarded
async def ved_fetch(max_length: int = 5000, start_index: int = 0, tab: str = "") -> str:
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

    cache_dir = paths.cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    _prune_cache(cache_dir)
    cache_path = cache_dir / f"fetch_{tab_id[:8]}.json"

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
async def ved_screenshot(name: str = "", full_page: bool = True, output_dir: str | None = None) -> str:
    """截图当前页面。

    Args:
        name: 可选的文件名前缀（留空则只用站点名+时间戳）。
        full_page: True = 整页，False = 当前视口。
        output_dir: 本次落盘目录（绝对路径），覆盖 --response-dir。

    Returns:
        文件路径是 <站点名>_<YYYYMMDD-HHMMSS>.png（给了 name 则是 <name>_<站点名>_<时间戳>.png）。
    """
    if not state._browser:
        return "Error: no browser session."

    try:
        page = await state._browser.get_current_page()
        if page is None:
            return "Error: no page available."
        save_dir = paths.resolve_response_dir(output_dir)
        path = naming.unique_path(save_dir, naming.shot_stem(page.url, name), ".png")
        await page.screenshot(path=str(path), full_page=full_page)
        return f"{state.current_prefix()}\nScreenshot saved: {path}"
    except paths.PathError as exc:
        return str(exc)
    except Exception as e:
        return f"Screenshot failed: {e}"


@state.mcp.tool()
@observation.guarded
async def ved_dom_tree(depth: int = limits.TREE_DEPTH, tab: str = "") -> str:
    """输出当前页面的 DOM 目录树（内存快照，含容器/字段/交互标记）。

    首次调用或页面导航后会自动重新扫描；此后从内存读取，不再调浏览器。

    Args:
        depth: 树的显示深度（默认 2，够看清结构；要细看传 4-8）。
        tab: CDP short ID（空 = 当前激活 tab）。

    Returns:
        格式化 DOM 树（超过上限会截断）。
    """
    tree = await _ensure_tree(tab)
    if tree is None:
        return "Error: no browser session."
    level = limits.clamp(depth, low=1, high=12, default=limits.TREE_DEPTH)
    return limits.truncate_text(
        f"{state.prefix(tree.tab_id)}\n{tree.format(level)}",
        hint="想更深：depth= 调大；定位单个节点用 ved_dom_locate / ved_dom_search",
    )


@state.mcp.tool()
@observation.guarded
async def ved_dom_search(
    text: str,
    tab: str = "",
    offset: int = 0,
    limit: int = limits.LIST_LIMIT,
) -> str:
    """在内存 DOM 树中搜索文本。

    不调浏览器，直接在保存的树结构里查找。返回匹配的节点路径和上下文。

    Args:
        text: 搜索关键字（匹配文本/属性/id，大小写不敏感）。
        tab: CDP short ID（空 = 当前激活 tab）。
        offset: 从第几处匹配开始（默认 0）。
        limit: 本次返回条数（默认 30）。

    Returns:
        分页的匹配节点路径列表；页脚给出续读用的 offset。
    """
    tree = await _ensure_tree(tab)
    if tree is None:
        return "Error: no browser session."
    matches = tree.search(text)
    if not matches:
        return f"{state.prefix(tree.tab_id)}\nNo matches in DOM tree."
    page, footer = limits.paginate(matches, offset, limit, unit="处匹配")
    lines = [state.prefix(tree.tab_id), f"DOM matches for '{text}':", ""]
    for path, node in page:
        summary = node.text[:60] if node.text else ""
        lines.append(f"  {path}" + (f'  "{summary}"' if summary else ""))
    lines.append(footer)
    return limits.truncate_text("\n".join(lines))


@state.mcp.tool()
@observation.guarded
async def ved_dom_locate(path: str, depth: int = 3, tab: str = "") -> str:
    """通过路径定位一个 DOM 节点。

    路径要**从根节点开始**（第一段必须匹配 ``html``）—— 例如
    ``html > body.win > div#app > div.feed-card``（可直接从 ved_dom_tree 的输出里抄）。
    段格式：``tag[.class][#id][:nth-child(n)]``，``>`` 分隔。

    Args:
        path: 节点路径（从 html 开始）。
        depth: 子树的显示深度（默认 3）。
        tab: CDP short ID（空 = 当前激活 tab）。

    Returns:
        节点子树（超过上限会截断）。
    """
    tree = await _ensure_tree(tab)
    if tree is None:
        return "Error: no browser session."
    node = tree.locate(path)
    if node is None:
        return (
            f"{state.prefix(tree.tab_id)}\nPath not found: {path}\n"
            "(路径要从 html 开始，例如：html > body > div#app)"
        )
    level = limits.clamp(depth, low=1, high=12, default=3)
    lines = [state.prefix(tree.tab_id), path]
    _walk(node, "", "", 0, level, lines)
    return limits.truncate_text("\n".join(lines), hint="想更深：depth= 调大")


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
        from veddata.dom import snapshot_tree
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
async def ved_cookies(all_domains: bool = False, all_info: bool = False, tab: str = "") -> str:
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
            value = limits.clip(c.get("value", ""))
            domain = c.get("domain", "")
            lines.append(f"  {name:<20} = {value} ({domain})")
        lines.append(f"(值超过 {limits.VALUE_CHARS} 字符会截断；要全量传 all_info=true)")

    return limits.truncate_text("\n".join(lines))


@state.mcp.tool()
@observation.guarded
async def ved_console(code: str = "", tail: int = 0, filter: str = "", tab: str = "") -> str:
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
                text = json.dumps(result, ensure_ascii=False, default=str)
            except Exception:
                text = str(result)
            return limits.truncate_text(
                text,
                limit=2000,
                hint="想取部分结果：在 JS 里先切好再返回（例如 JSON.stringify(x).slice(0, 500)）",
            )
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
        lines.append(f"[{m['type']}] {limits.clip(m['text'], 500)}")
    return limits.truncate_text("\n".join(lines), hint="用 tail= 只看最近几条、filter= 过滤")
