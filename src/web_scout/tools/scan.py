"""Scan tools — comprehensive page data source discovery."""

import json as _json
import time

from web_scout import state
from web_scout.browser import BrowserSession
from web_scout.network_pool import NetworkPool
from web_scout.dom import DOMScanner


@state.mcp.tool()
def scout_scan(mode: str = "all", keyword: str | None = None, url: str | None = None) -> str:
    """Comprehensive page data source scanner with two modes.

    MODE "all" — full page scan (default):
      1. Network APIs — XHR/Fetch requests already captured by the listener
      2. SSR Embedded JSON — window.__INITIAL_STATE__, __NEXT_DATA__, etc.
      3. DOM Containers — repeated HTML structures (card layouts, list items)

    MODE "dom" — keyword-targeted DOM scan:
      Searches DOM for containers matching the keyword.

    Args:
        mode: "all" for full scan, "dom" for keyword-targeted DOM scan.
        keyword: For mode "dom" — search keyword.
        url: For mode "dom" — optional URL to open before scanning.

    Returns:
        Data source summary for mode "all", or container list for mode "dom".
    """
    if mode == "dom" and url:
        return _scan_dom_with_url(url, keyword or "")
    elif mode == "dom":
        return _scan_dom_keyword(keyword or "")
    else:
        return _scan_all()


def _scan_all() -> str:
    if not state._browser:
        return "Error: call scout_open first."
    if state._login_pending:
        return "Error: call scout_login() first."

    tab_id = state._browser.current_tab_id()
    pool = state.get_pool()

    time.sleep(3)
    before_count = len(pool.get_by_tab(tab_id)) if pool else 0
    if pool:
        pool.step(timeout=5.0, tab=state._browser.get_current_tab())
    records = pool.get_by_tab(tab_id) if pool else []
    new_count = len(records) - before_count

    dom = DOMScanner(state._browser.get_current_tab())
    state._dom_scanners[tab_id] = dom
    containers = dom.find_containers()
    dom_count = len(dom.containers_cache)
    total_api = len(records)

    parts = [state.prefix(tab_id), ""]

    parts.append("=== Network APIs ===")
    if total_api > 0:
        api_list = pool.list_apis(tab_id=tab_id) if pool else ""
        lines = api_list.split("\n") if api_list else []
        parts.append(f"{total_api} total ({new_count} new since last check):")
        parts.extend(lines[:8])
        if len(lines) > 8:
            parts.append(f"... and {len(lines) - 8} more")
    else:
        parts.append("0 — this may be a pure SSR page, data is in HTML/DOM. Use scout_search() to find keywords.")
    parts.append("")

    parts.append(f"=== DOM Structure ({dom_count} containers) ===")
    try:
        tab = state._browser.get_current_tab()
        js = """
        (function() {
            var r = {};
            var m = document.querySelector('meta[name="description"]');
            if (m) r.meta = m.getAttribute('content').substring(0, 200);
            var h1s = document.querySelectorAll('h1');
            r.h1 = Array.from(h1s).slice(0,3).map(function(e){return e.textContent.trim().substring(0,100)});
            var h2s = document.querySelectorAll('h2');
            r.h2 = Array.from(h2s).slice(0,3).map(function(e){return e.textContent.trim().substring(0,100)});
            return JSON.stringify(r);
        })()
        """
        raw = tab.run_js(js)
        if raw and isinstance(raw, str):
            tags = _json.loads(raw)
            if tags.get("meta"):
                parts.append(f"  desc: {tags['meta'][:150]}")
            for tag_name in ("h1", "h2"):
                if tags.get(tag_name):
                    for t in tags[tag_name]:
                        parts.append(f"  {tag_name}: {t[:120]}")
    except Exception:
        pass

    if dom_count > 0:
        parts.append("  Containers:")
        for i, c in enumerate(dom.containers_cache[:5]):
            cls_name = c.get("selector", c.get("class", "?"))[:40]
            count = c.get("count", c.get("num", "?"))
            samples = c.get("samples", c.get("fields", []))
            sample_str = ", ".join([s.get("name", s)[:15] if isinstance(s, dict) else str(s)[:15] for s in samples[:6]])
            parts.append(f"  [{i+1}] {cls_name} x{count}")
            if sample_str:
                parts.append(f"      |-- {sample_str}")
    parts.append("")

    embedded_count = 0
    parts.append("=== Embedded JSON (SSR) ===")
    parts.append(f"{embedded_count}")
    parts.append("")
    parts.append("---")
    return "\n".join(parts)


def _scan_dom_keyword(keyword: str) -> str:
    if not state._browser:
        return "Error: call scout_open first."
    if not keyword.strip():
        return "Keyword cannot be empty."
    tab_id = state._browser.current_tab_id()
    dom = state._dom_scanners.get(tab_id)
    if not dom:
        dom = DOMScanner(state._browser.get_current_tab())
        state._dom_scanners[tab_id] = dom
    result = dom.scan_by_keyword(keyword)
    return f"{state.current_prefix()}\n{result}"


def _scan_dom_with_url(url: str, keyword: str) -> str:
    if not state._browser:
        state._browser = BrowserSession()
    pool = state.get_pool()
    if not pool:
        pool = NetworkPool()
        state.set_pool(pool)
    try:
        state._browser.open(url)
        tab = state._browser.get_current_tab()
        pool.start_tab(tab)
        time.sleep(2)
        dom = DOMScanner(state._browser.get_current_tab())
        result = dom.scan_by_keyword(keyword)
        return f"{state.current_prefix()}\n{result}"
    except Exception as e:
        return f"scout_scan failed: {e}"
