"""Act tools — page interaction: input/scroll/click/select chain, login."""

import asyncio

from veddata import gate, observation, state


def _is_selector(target: str) -> bool:
    """``css=`` / ``xpath=`` / ``//`` 开头 → 当选择器；其余按可见文本匹配。"""
    return target.startswith(("css=", "xpath=")) or target.startswith("//")


async def _find_locator(page, text, kinds):
    """按 locator 找一个可点击的元素。

    顺序：**选择器**（``target="css=a[href*='/download/']"`` 或 ``target="//a[...]"``）
    → placeholder（input）→ role（button/link）→ has_text 兜底。
    选择器命中就用它（精确），否则退回文本匹配。
    返回第一个能成功点击（timeout 3s）的 locator，找不到返回 None。
    """
    if _is_selector(text):
        try:
            locator = page.locator(text).first
            await locator.click(timeout=3000)
            return locator
        except Exception:
            return None

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
    selector = kinds if isinstance(kinds, str) else ",".join(kinds)
    candidates.append(page.locator(selector).filter(has_text=text).first)

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
@observation.guarded
async def ved_act(
    action: str = "",
    value: str | None = None,
    target: str | None = None,
    actions: list | None = None,
) -> str:
    """Execute actions on the page: input, scroll, click, or select.

    Two modes:
    1. Single step: ved_act("scroll", "bottom")
       ved_act("input", "python教程", target="搜索")
       ved_act("click", target="下一页")
       ved_act("select", "最多播放", target="综合排序")
       ved_act("click", target="css=a[href*='/download/']")     ← target 也接受选择器
       ved_act("click", target="//a[contains(@href,'/download/')]")

    2. Chain: ved_act(actions=[
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
        return "Error: no browser session."

    page = await state._browser.get_current_page()
    if page is None:
        return "Error: no page available."
    tab_id = state._browser.current_tab_id()
    pool = state.get_pool()

    if actions:
        report_lines = [f"{state.prefix(tab_id)}", f"Action chain ({len(actions)} steps):\n"]
        for step in actions:
            report_lines.append(await _do_action(page, pool, step))
        return await _finish(page, tab_id, "\n".join(report_lines))

    step = {"action": action}
    if value is not None:
        step["value"] = value
    if target is not None:
        step["target"] = target
    report_lines = [state.prefix(tab_id), ""]
    report_lines.append(await _do_action(page, pool, step))
    return await _finish(page, tab_id, "\n".join(report_lines))


async def _finish(page, tab_id: str, report: str) -> str:
    """动作收尾：先看有没有撞上人机门，再把状态账本推到当前版本。

    撞上人机门（登录 / 验证 / 风控）**不重试、不等待** —— 把话说明白交给用户，
    用户处理完让 AI 继续（协作协议见 gate.py）。
    """
    block = await gate.detect_async(page, tab_id)
    observation.observe()            # 我们自己发起的动作：返回的就是最新状态
    if block is not None and block.hard:
        return gate.format_gate(block, state.prefix(tab_id))
    if block is not None:
        return f"{gate.format_gate(block, state.prefix(tab_id))}\n\n{report}"
    return report
