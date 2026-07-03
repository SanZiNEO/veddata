"""Act tools — page interaction: input/scroll/click/select chain, login."""

import time

from web_scout import state
from web_scout.login import LoginDetector


def _find_el_by_text(tab, text, tags="a,button,input,select,span"):
    for tag in tags.split(','):
        for el in tab.eles(f'tag:{tag}'):
            try:
                if not el.states.is_displayed:
                    continue
                combined = (
                    (el.text or '')
                    + ' ' + (el.attr('placeholder') or '')
                    + ' ' + (el.attr('aria-label') or '')
                )
                if text in combined:
                    return el
            except Exception:
                pass
    return None


def _do_input(tab, value, target):
    el = _find_el_by_text(tab, target, "input,textarea")
    if not el:
        return f"Input '{target}' not found"
    el.click()
    time.sleep(0.3)
    el.clear()
    el.input(value)
    tab.actions.key_down('ENTER').key_up('ENTER')
    return f"Input '{value}' into '{target}'"


def _do_scroll(tab, value):
    if value in (None, "bottom"):
        tab.scroll.to_bottom()
        return "Scrolled to bottom"
    elif value == "top":
        tab.scroll.to_top()
        return "Scrolled to top"
    elif value == "down":
        vp = tab.run_js("return window.innerHeight")
        tab.scroll.down(vp)
        return f"Scrolled down {vp}px"
    elif value == "up":
        vp = tab.run_js("return window.innerHeight")
        tab.scroll.up(vp)
        return f"Scrolled up {vp}px"
    elif value and value.lstrip("-").isdigit():
        px = int(value)
        if px >= 0:
            tab.scroll.down(px)
        else:
            tab.scroll.up(abs(px))
        return f"Scrolled {'down' if px >= 0 else 'up'} {abs(px)}px"
    else:
        return f"Unsupported scroll value: '{value}'"


def _do_click(tab, target):
    el = _find_el_by_text(tab, target, "a,button,span")
    if not el:
        return f"Click '{target}' not found"
    el.click()
    return f"Clicked '{target}'"


def _do_select(tab, value, target):
    el = _find_el_by_text(tab, target, "a,button,div")
    if not el:
        return f"Select trigger '{target}' not found"
    el.click()
    time.sleep(0.3)
    opt = _find_el_by_text(tab, value, "a,li,span,option")
    if not opt:
        return f"Option '{value}' not found"
    opt.click()
    return f"Selected '{value}' in '{target}'"


def _list_new_apis(before: list, pool) -> list[dict]:
    before_paths = {(r["method"], r["path"]) for r in before}
    return [r for r in pool.api_records if (r["method"], r["path"]) not in before_paths]


def _do_action(tab, pool, step):
    a = step
    action = a.get("action", "")
    value = a.get("value")
    target = a.get("target")

    before = list(pool.api_records) if pool else []

    if action == "input":
        desc = _do_input(tab, value, target)
    elif action == "scroll":
        desc = _do_scroll(tab, value)
    elif action == "click":
        desc = _do_click(tab, target)
    elif action == "select":
        desc = _do_select(tab, value, target)
    else:
        return f"  [{action}] Unsupported action: {action} → +0 new APIs"

    time.sleep(1.5)
    if pool:
        pool.step(timeout=3.0, tab=tab)
    new_apis = _list_new_apis(before, pool) if pool else []
    lines = [f"  [{action}] {desc} → +{len(new_apis)} new APIs"]
    for api in new_apis[:6]:
        lines.append(f"    {api['method'].ljust(6)} {api['path']}")
    if len(new_apis) > 6:
        lines.append(f"    ... and {len(new_apis) - 6} more")
    return "\n".join(lines)


@state.mcp.tool()
def scout_act(
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

    tab = state._browser.get_current_tab()
    tab_id = state._browser.current_tab_id()
    pool = state.get_pool()

    if actions:
        report_lines = [f"{state.prefix(tab_id)}", f"Action chain ({len(actions)} steps):\n"]
        for step in actions:
            report_lines.append(_do_action(tab, pool, step))
        total = sum(len(a) for a in report_lines)
        return "\n".join(report_lines)

    step = {"action": action}
    if value is not None:
        step["value"] = value
    if target is not None:
        step["target"] = target
    report_lines = [state.prefix(tab_id), ""]
    report_lines.append(_do_action(tab, pool, step))
    return "\n".join(report_lines)


@state.mcp.tool()
def scout_login(timeout: int = 300) -> str:
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

    detector = LoginDetector(state._browser.get_current_tab())
    result = detector.wait_for_login(timeout)

    if result:
        text = state._browser.get_text()
        return (f"{state.current_prefix()}\n"
                f"Login successful!\n\n"
                f"Page text:\n{text[:2000]}\n\n"
                f"Call scout_scan(mode='all') to capture API endpoints.")
    else:
        return f"Login timeout ({timeout}s). Please try again."
