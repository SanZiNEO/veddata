"""Act tools — page interaction: input/scroll/click/select chain, login."""

import asyncio

from web_scout import state
from web_scout.login import LoginDetector


async def _find_locator(page, text, kinds):
    """按文本/占位符找一个可点击的 locator。

    尝试顺序：placeholder（input）→ role（button/link）→ has_text 兜底。
    返回第一个能成功点击（timeout 3s）的 locator，找不到返回 None。
    """
    candidates = []
    if kinds in ("input,textarea",):
        candidates.append(page.get_by_placeholder(text).first)
        candidates.append(page.locator("input,textarea").filter(has_text=text).first)
    if "button" in kinds:
        candidates.append(page.get_by_role("button", name=text).first)
    if "a" in kinds:
        candidates.append(page.get_by_role("link", name=text).first)
    if "span" in kinds or kinds in ("a,button,div", "a,li,span,option"):
        candidates.append(page.get_by_text(text, exact=False).first)
    candidates.append(page.locator(",".join(kinds)).filter(has_text=text).first)

    for locator in candidates:
        try:
            await locator.click(timeout=3000)
            return locator
        except Exception:
            continue
    return None


async def _do_input(page, value, target):
    locator = await _find_locator(page, target, "input,textarea")
    if locator is None:
        return f"Input '{target}' not found"
    await locator.fill(value)
    await page.keyboard.press("Enter")
    return f"Input '{value}' into '{target}'"


async def _do_scroll(page, value):
    if value in (None, "bottom"):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        return "Scrolled to bottom"
    elif value == "top":
        await page.evaluate("window.scrollTo(0, 0)")
        return "Scrolled to top"
    elif value == "down":
        await page.evaluate("window.scrollBy(0, window.innerHeight)")
        return "Scrolled down one viewport"
    elif value == "up":
        await page.evaluate("window.scrollBy(0, -window.innerHeight)")
        return "Scrolled up one viewport"
    elif value and value.lstrip("-").isdigit():
        px = int(value)
        await page.evaluate(f"window.scrollBy(0, {px})")
        return f"Scrolled {'down' if px >= 0 else 'up'} {abs(px)}px"
    else:
        return f"Unsupported scroll value: '{value}'"


async def _do_click(page, target):
    locator = await _find_locator(page, target, "a,button,span")
    if locator is None:
        return f"Click '{target}' not found"
    return f"Clicked '{target}'"


async def _do_select(page, value, target):
    locator = await _find_locator(page, target, "a,button,div")
    if locator is None:
        return f"Select trigger '{target}' not found"
    await asyncio.sleep(0.3)
    opt = await _find_locator(page, value, "a,li,span,option")
    if opt is None:
        return f"Option '{value}' not found"
    return f"Selected '{value}' in '{target}'"


def _list_new_apis(before: list, pool) -> list[dict]:
    before_paths = {(r["method"], r["path"]) for r in before}
    return [r for r in pool.api_records if (r["method"], r["path"]) not in before_paths]


async def _do_action(page, pool, step):
    a = step
    action = a.get("action", "")
    value = a.get("value")
    target = a.get("target")

    before = list(pool.api_records) if pool else []
    if pool:
        pool.set_trigger_context(f"{action}:{target or ''}")

    if action == "input":
        desc = await _do_input(page, value, target)
    elif action == "scroll":
        desc = await _do_scroll(page, value)
    elif action == "click":
        desc = await _do_click(page, target)
    elif action == "select":
        desc = await _do_select(page, value, target)
    else:
        return f"  [{action}] Unsupported action: {action} → +0 new APIs"

    await page.wait_for_timeout(1500)
    new_apis = _list_new_apis(before, pool) if pool else []
    lines = [f"  [{action}] {desc} → +{len(new_apis)} new APIs"]
    for api in new_apis[:6]:
        lines.append(f"    {api['method'].ljust(6)} {api['path']}")
    if len(new_apis) > 6:
        lines.append(f"    ... and {len(new_apis) - 6} more")
    return "\n".join(lines)


@state.mcp.tool()
async def scout_act(
    action: str = "",
    value: str | None = None,
    target: str | None = None,
    actions: list | None = None,
) -> str:
    """Execute actions on the page: input, scroll, click, or select.

    Two modes:
    1. Single step: scout_act("scroll", "bottom")
       scout_act("input", "python教程", target="搜索")
       scout_act("click", target="下一页")
       scout_act("select", "最多播放", target="综合排序")

    2. Chain: scout_act(actions=[
         {"action": "input", "value": "python教程", "target": "搜索"},
         {"action": "scroll", "value": "bottom"},
         {"action": "click", "target": "最多播放"},
       ])

    Each step reports new API method + path inline so AI sees them immediately.

    Args:
        action: "input", "scroll", "click", or "select" (single mode).
        value: Text input or scroll target (bottom/top/down/up/px).
        target: Visible text of the target element.
        actions: List of action dicts for chain mode.

    Returns:
        Status with new API counts and paths per step.
    """
    if not state._browser:
        return "Error: call scout_open first."

    page = await state._browser.get_current_page()
    if page is None:
        return "Error: no page available."
    tab_id = state._browser.current_tab_id()
    pool = state.get_pool()

    if actions:
        report_lines = [f"{state.prefix(tab_id)}", f"Action chain ({len(actions)} steps):\n"]
        for step in actions:
            report_lines.append(await _do_action(page, pool, step))
        return "\n".join(report_lines)

    step = {"action": action}
    if value is not None:
        step["value"] = value
    if target is not None:
        step["target"] = target
    report_lines = [state.prefix(tab_id), ""]
    report_lines.append(await _do_action(page, pool, step))
    return "\n".join(report_lines)


@state.mcp.tool()
async def scout_login(timeout: int = 300) -> str:
    """Wait for the user to manually log in via the browser window.

    Detects login by polling cookies: if cookie names change or ≥2 values
    change simultaneously, login is detected.  Works across all sites
    without site-specific logic.

    Args:
        timeout: Maximum wait time in seconds (default 300).

    Returns:
        Status message with refreshed page text.
    """
    if not state._browser:
        return "Error: call scout_open first."

    page = await state._browser.get_current_page()
    if page is None:
        return "Error: no page available."

    detector = LoginDetector(page)
    result = await detector.wait_for_login(timeout)

    if result:
        text = await state._browser.get_text()
        return (f"{state.current_prefix()}\n"
                f"Login successful!\n\n"
                f"Page text:\n{text[:2000]}\n\n"
                f"Call scout_scan(mode='all') to capture API endpoints.")
    else:
        return f"Login timeout ({timeout}s). Please try again."
