"""工具链：把已有工具按顺序交给服务端连续执行 —— 消除回合制交互的观测空窗。

要解决的两个问题
----------------
1. **别错过**：MCP 每个动作一次模型往返，两次调用之间隔着模型的思考时间，
   期间发生的请求/日志/中间态早就过去了。链把"动作 + 等待 + 取样"在**服务端**
   连续跑完，中间不经过模型。
2. **给因果**：AI 事后不知道"这个请求是哪个动作触发的"。链里每个动作步骤
   自动算**差分**（新增请求 / 新增控制台 / DOM 变化），报告直接写清楚。

步骤形态（三种）
----------------
- 工具调用：``{"tool": "ved_act", "args": {"action": "click", "target": "下一页"}}``
- 等待：``{"wait": {"ms": 400}}`` / ``{"wait": {"network": "**/joblist**", "timeout": 8}}``
  / ``{"wait": {"network_idle": 800, "timeout": 8}}`` / ``{"wait": {"element": "#list .card", "state": "visible"}}``
- 重复（一层，翻页用）：``{"repeat": {"times": 5, "steps": [...]}}``

规矩
----
- **白名单**：只允许既有工具里的动作/读取类；``ved_close`` / ``ved_chain`` 禁掉。
- **每步都过同一套门禁**：链不是后门。链自己造成的状态变化在内部视为已知
  （每步后自动建档），但**工具之外**的改动（页面自跳/用户开标签）会让链停下。
- **撞上人机门**（登录/验证/风控）→ 停在该步，返回 chain_id，用户处理完用
  ``ved_chain(resume="<id>:<step>")`` 续跑，**不重放**已完成的动作。
- 上限：``max_steps``(30) / ``repeat.times``(20) / 单步超时 / 总时长。
"""

from __future__ import annotations

import asyncio
import fnmatch
import random
import time
import uuid
from dataclasses import dataclass, field

from veddata import limits, naming, observation, state

MODULES = ("veddata.tools.act", "veddata.tools.discover", "veddata.tools.navigate",
           "veddata.tools.observe", "veddata.tools.scan")

# 允许在链里调用的工具（动作 + 读取）；其余一律拒绝
ALLOWED = {
    "ved_open", "ved_goto", "ved_tabs", "ved_tab_switch", "ved_status",
    "ved_act", "ved_watch",
    "ved_apis", "ved_inspect", "ved_peek", "ved_request", "ved_search", "ved_context",
    "ved_trace_value", "ved_list_scripts", "ved_search_scripts", "ved_script_source",
    "ved_console", "ved_cookies", "ved_dom_tree", "ved_dom_search", "ved_dom_locate",
    "ved_fetch", "ved_screenshot", "ved_scan", "ved_export", "ved_export_all",
}
BLOCKED = {"ved_close", "ved_chain"}

# 会改变页面状态的工具：动作前后要算差分、之后要查人机门
PAGE_TOUCHING = {"ved_act", "ved_goto", "ved_tab_switch", "ved_peek"}

MAX_STEPS = 30
MAX_REPEAT = 20
STEP_TIMEOUT = 30.0
TOTAL_TIMEOUT = 300.0
MAX_RUNS = 20

_runs: dict[str, "ChainRun"] = {}


@dataclass
class StepResult:
    index: int
    label: str
    ok: bool
    detail: str = ""
    ms: int = 0
    diff: list[str] = field(default_factory=list)


@dataclass
class ChainRun:
    id: str
    steps: list
    results: list[StepResult] = field(default_factory=list)
    stop_reason: str = ""
    stop_index: int = 0            # 停在（或即将执行）第几步（1-based）
    done: bool = False

    def next_step(self) -> int:
        """续跑起点（1-based）。"""
        return max(1, self.stop_index or (len(self.results) + 1))


class ChainError(Exception):
    """链本身的问题（步骤不合法、工具不允许）。"""


# ---------------- 步骤展开 ----------------

def expand(steps: list, _depth: int = 0) -> list[dict]:
    """把 repeat 展开成扁平步骤列表（只允许一层 repeat）。"""
    flat: list[dict] = []
    for step in steps or []:
        if not isinstance(step, dict):
            raise ChainError(f"step must be an object, got: {type(step).__name__}")
        if "repeat" in step:
            if _depth:
                raise ChainError("nested repeat is not supported")
            block = step["repeat"] or {}
            times = int(block.get("times", 1))
            if not 1 <= times <= MAX_REPEAT:
                raise ChainError(f"repeat.times must be 1..{MAX_REPEAT}, got {times}")
            for round_index in range(times):
                for inner in expand(block.get("steps") or [], _depth + 1):
                    flat.append({**inner, "_round": round_index + 1})
        elif "tool" in step:
            name = str(step["tool"])
            if name in BLOCKED or name not in ALLOWED:
                raise ChainError(f"tool not allowed in a chain: {name}")
            flat.append({"tool": name, "args": step.get("args") or {}, "_round": step.get("_round", 0)})
        elif "wait" in step:
            flat.append({"wait": step["wait"] or {}, "_round": step.get("_round", 0)})
        else:
            raise ChainError(f"step needs 'tool', 'wait' or 'repeat': {step}")
    return flat


def _brief(value) -> str:
    """参数摘要：URL 只留路径（否则几条 goto 长得一模一样，报告里分不出是哪一步）。"""
    text = str(value)
    if text.startswith(("http://", "https://")):
        rest = text.split("//", 1)[1]
        text = "/" + rest.split("/", 1)[1] if "/" in rest else rest
    return text[:48]


def label_of(step: dict) -> str:
    if "tool" in step:
        args = step.get("args") or {}
        brief = ", ".join(f"{k}={_brief(v)}" for k, v in list(args.items())[:2])
        round_tag = f" [第{step['_round']}轮]" if step.get("_round") else ""
        return f"{step['tool']}({brief}){round_tag}"
    wait = step.get("wait") or {}
    return "wait(" + ", ".join(f"{k}={v}" for k, v in list(wait.items())[:2]) + ")"


# ---------------- 差分（因果） ----------------

def _snapshot() -> dict:
    """当前"该看到的东西"的计数：请求数 + 控制台条数（拿不到就是 None）。"""
    pool = state.get_pool()
    tab_id = state._browser.current_tab_id() if state._browser else ""
    return {
        "tab_id": tab_id,
        "requests": len(pool.get_by_tab(tab_id)) if pool and tab_id else 0,
        "pool": pool,
    }


def _diff(before: dict, after: dict) -> list[str]:
    """算这步动作造成的因果：新增了哪些请求。"""
    lines: list[str] = []
    pool = after.get("pool")
    tab_id = after.get("tab_id") or ""
    fresh = after.get("requests", 0) - before.get("requests", 0)
    if fresh > 0 and pool is not None:
        try:
            records = pool.get_by_tab(tab_id)[before.get("requests", 0):]
        except Exception:
            records = []
        grouped: dict[str, int] = {}
        for record in records:
            path = naming.endpoint_name(record.get("url", ""), fallback="request")
            grouped[path] = grouped.get(path, 0) + 1
        detail = ", ".join(f"{name} ×{count}" if count > 1 else name for name, count in list(grouped.items())[:4])
        lines.append(f"+{fresh} requests: {limits.clip(detail, 120)}")
    return lines


# ---------------- 工具解析 ----------------

def _resolve(name: str):
    import importlib

    for module_name in MODULES:
        module = importlib.import_module(module_name)
        candidate = getattr(module, name, None)
        if candidate is not None:
            return getattr(candidate, "fn", getattr(candidate, "__wrapped__", candidate))
    raise ChainError(f"tool not found: {name}")


# ---------------- 等待 ----------------

async def _wait(step: dict, started_at: float) -> str:
    """执行一个 wait 步骤，返回人类可读的结果。"""
    wait = step.get("wait") or {}
    timeout = float(wait.get("timeout", 10.0))

    if "ms" in wait:
        await asyncio.sleep(min(float(wait["ms"]), 60_000) / 1000)
        return f"slept {wait['ms']}ms"

    if "network" in wait:
        pattern = str(wait["network"])
        pool = state.get_pool()
        tab_id = state._browser.current_tab_id() if state._browser else ""
        baseline = len(pool.get_by_tab(tab_id)) if pool and tab_id else 0
        deadline = time.time() + timeout
        while time.time() < deadline:
            records = pool.get_by_tab(tab_id) if pool and tab_id else []
            for record in records[baseline:]:
                if fnmatch.fnmatch(record.get("url", ""), pattern) or pattern in record.get("url", ""):
                    return f"matched {limits.clip(record.get('url', ''), 80)}"
            await asyncio.sleep(0.1)
        return f"timeout waiting for {pattern}"

    if "network_idle" in wait:
        quiet = float(wait["network_idle"]) / 1000
        pool = state.get_pool()
        tab_id = state._browser.current_tab_id() if state._browser else ""
        last_count = len(pool.get_by_tab(tab_id)) if pool and tab_id else 0
        last_change = time.time()
        deadline = time.time() + timeout
        while time.time() < deadline:
            await asyncio.sleep(0.1)
            count = len(pool.get_by_tab(tab_id)) if pool and tab_id else 0
            if count != last_count:
                last_count, last_change = count, time.time()
            elif time.time() - last_change >= quiet:
                return f"network idle for {int(quiet * 1000)}ms"
        return "timeout waiting for network idle"

    if "element" in wait:
        selector = str(wait["element"])
        want = str(wait.get("state", "visible"))
        page = await state._browser.get_current_page() if state._browser else None
        if page is None:
            return "no page to wait on"
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                count = await page.locator(selector).count()
                visible = count > 0 and await page.locator(selector).first.is_visible()
            except Exception:
                count, visible = 0, False
            if (want == "visible" and visible) or (want == "hidden" and not visible):
                return f"element {selector} is {want}"
            await asyncio.sleep(0.15)
        return f"timeout waiting for {selector} to be {want}"

    return "nothing to wait for"


# ---------------- 执行 ----------------

async def run(steps: list, *, on_error: str = "stop", step_delay_ms: int = 0,
              max_steps: int = MAX_STEPS, total_timeout: float = TOTAL_TIMEOUT,
              index_offset: int | None = None, resume_of: ChainRun | None = None,
              caller=None) -> ChainRun:
    """顺序执行链，返回 ChainRun（结果留服务端，调用方只回压缩报告）。

    ``index_offset`` 不给时：续跑自动接在已有结果之后（步号单调递增，便于对照报告）。
    """
    flat = expand(steps)
    run_record = resume_of or ChainRun(id=uuid.uuid4().hex[:8], steps=steps)
    base = index_offset if index_offset is not None else (len(run_record.results) if resume_of else 0)
    if len(flat) + base > max_steps:
        raise ChainError(f"too many steps: {len(flat) + base} > {max_steps}")

    call = caller or _resolve
    started = time.time()

    for offset, step in enumerate(flat):
        index = base + offset + 1
        if time.time() - started > total_timeout:
            run_record.stop_reason = f"total timeout {total_timeout:.0f}s"
            run_record.stop_index = index
            return run_record

        # 工具之外发生的变化 → 停（链不能拿旧认知继续动）
        if step.get("tool") in PAGE_TOUCHING and observation.ledger().stale:
            run_record.stop_reason = ("browser state changed outside the chain "
                                      f"({'; '.join(observation.ledger().reasons) or 'unknown'})")
            run_record.stop_index = index
            return run_record

        step_started = time.time()
        label = label_of(step)
        try:
            if "wait" in step:
                detail = await asyncio.wait_for(_wait(step, step_started), timeout=STEP_TIMEOUT + 10)
                result = StepResult(index, label, not detail.startswith("timeout"), detail)
            else:
                name = step["tool"]
                if step_delay_ms:
                    jitter = random.randint(0, max(1, step_delay_ms // 2))
                    await asyncio.sleep((step_delay_ms + jitter) / 1000)
                before = _snapshot() if name in PAGE_TOUCHING else None
                # caller 语义：返回"可调用的工具"（默认 _resolve）；注入的假 caller 也可以直接返回结果
                resolved = call(name)
                value = resolved(**step["args"]) if callable(resolved) else resolved
                # 解包装饰器层：可能是协程 / 普通函数 / 已经算好的值（ved_apis 等同步工具）
                for _ in range(3):
                    if hasattr(value, "__await__"):
                        value = await asyncio.wait_for(value, timeout=STEP_TIMEOUT)
                    elif callable(value):
                        value = value()
                    else:
                        break
                output = value
                text = output if isinstance(output, str) else str(output)
                diff = _diff(before, _snapshot()) if before is not None else []
                result = StepResult(index, label, True, limits.clip(text.splitlines()[0] if text else "", 120), diff=diff)
                if name in PAGE_TOUCHING and state._browser is not None:
                    observation.observe()          # 链自己造成的变化 → 内部视为已知
                    page = await state._browser.get_current_page()
                    tab_id = state._browser.current_tab_id()
                    if page is not None:
                        from veddata import gate
                        block = await gate.detect_async(page, tab_id)
                        if block is not None and block.hard:
                            run_record.results.append(result)
                            run_record.stop_reason = "需要人工：" + (block.evidence[0] if block.evidence else block.kind)
                            run_record.stop_index = index + 1
                            return run_record
        except asyncio.TimeoutError:
            result = StepResult(index, label, False, f"step timeout {STEP_TIMEOUT:.0f}s")
        except Exception as exc:                                               # noqa: BLE001
            result = StepResult(index, label, False, f"{type(exc).__name__}: {str(exc)[:140]}")

        result.ms = int((time.time() - step_started) * 1000)
        run_record.results.append(result)
        if not result.ok and on_error == "stop":
            run_record.stop_reason = f"step {index} failed: {result.detail}"
            run_record.stop_index = index
            return run_record

    run_record.done = True
    run_record.stop_index = base + len(flat) + 1
    return run_record


# ---------------- 报告 ----------------

def render(run_record: ChainRun) -> str:
    lines = [f"chain {run_record.id}: {len(run_record.results)}/{len(expand(run_record.steps))} steps"
             + (" (done)" if run_record.done else f" (stopped at step {run_record.stop_index})")]
    for item in run_record.results:
        mark = "ok  " if item.ok else "FAIL"
        lines.append(f"  {item.index:>2}. {mark} {item.label}  {item.ms}ms  {item.detail}")
        for line in item.diff:
            lines.append(f"          ↳ {line}")            # 因果：这步动作触发了什么
    if run_record.stop_reason:
        lines.append(f"  stopped at step {run_record.stop_index}: {run_record.stop_reason}")
    return limits.truncate_text("\n".join(lines), hint="细节留在服务端：ved_apis / ved_inspect / ved_watch(collect)")


def remember(run_record: ChainRun) -> None:
    _runs[run_record.id] = run_record
    while len(_runs) > MAX_RUNS:
        _runs.pop(next(iter(_runs)))


def get_run(chain_id: str) -> ChainRun | None:
    return _runs.get(chain_id)


def list_runs() -> str:
    if not _runs:
        return "No chains yet."
    lines = []
    for run_id, item in _runs.items():
        state_text = "done" if item.done else f"stopped@{item.stop_index}"
        lines.append(f"  {run_id}  {len(item.results)} steps  {state_text}"
                     + (f"  {item.stop_reason}" if item.stop_reason else ""))
    return "Chains:\n" + "\n".join(lines)
