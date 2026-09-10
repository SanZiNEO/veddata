"""工具链的 MCP 入口（核心逻辑在 chain.py，保持可单测、可脱浏览器测试）。"""

from __future__ import annotations

from veddata import state
from veddata.tools import chain as core


@state.mcp.tool()
async def ved_chain(
    steps: list | None = None,
    resume: str = "",
    on_error: str = "stop",
    step_delay_ms: int = 0,
) -> str:
    """工具链：一次把多个工具按顺序交给服务端连续执行。

    解决 MCP 回合制的两个硬伤：
    1. **别错过** —— 动作与等待/取样在服务端紧挨着跑，中间不经过模型，
       瞬时事件（请求/日志/中间态/弹窗）不会被回合间隔吞掉。
    2. **给因果** —— 每个动作步骤自动算差分，报告里直接写"+3 requests: …"，
       AI 不用再靠"点前点后各取一次"去猜哪个请求是哪个动作触发的。

    步骤（三种写法）：
      {"tool": "ved_act", "args": {"action": "click", "target": "下一页"}}
      {"wait": {"network": "**/joblist**", "timeout": 8}}
         wait 支持：ms / network（等指定请求出现）/ network_idle（网络静默）/ element(+state=visible|hidden)
      {"repeat": {"times": 5, "steps": [ ... ]}}          # 只允许一层，翻页用

    典型链路（翻页抓接口：现在 12+ 回合 → 2 回合）：
      ved_chain(steps=[
        {"tool": "ved_open"},
        {"tool": "ved_goto", "args": {"url": "https://…"}},
        {"tool": "ved_watch", "args": {"observations": [{"type": "request", "pattern": "**/api/**"}]}},
        {"tool": "ved_act", "args": {"action": "click", "target": "下一页"}},
        {"wait": {"network_idle": 800, "timeout": 10}},
        {"tool": "ved_watch", "args": {"collect": True, "timeout": 10}},
      ])

    行为约定：
      - 撞上登录/验证/风控 → 停在该步；用户处理完用 ved_chain(resume="<id>:<步号>") 续跑，**不重放**前面动作
      - 状态被工具之外改动（页面自跳 / 用户开标签页）→ 停，并说明原因
      - 每步都过和单独调用时同一套门禁（链不是后门）
      - 只允许既有工具里的动作/读取类；ved_close 与 ved_chain 自身禁用
      - 上限：30 步 / repeat 20 次 / 单步 30s / 整链 300s
      - 报告每步一行 + 因果差分，细节留服务端（用 ved_apis / ved_inspect / ved_watch(collect) 取）

    Args:
        steps: 步骤列表。不传且 resume 为空时，列出最近执行过的链。
        resume: "<chain_id>:<步号>" —— 从该步继续跑同一条链。
        on_error: "stop"（默认）或 "continue"。
        step_delay_ms: 步间基础延迟（毫秒，另加 0~50% 随机抖动，贴近人的交互节奏）。

    Returns:
        压缩报告：每步状态 + 因果差分 + 耗时；中断时给出停止原因与续跑指令。
    """
    try:
        if resume:
            chain_id, _, from_step = resume.partition(":")
            record = core.get_run(chain_id.strip())
            if record is None:
                return f"chain not found: {chain_id}（用 ved_chain() 看最近执行过的链）"
            flat = core.expand(record.steps)
            start = int(from_step) if from_step.strip().isdigit() else record.next_step()
            start = max(1, min(start, len(flat) + 1))
            if start > len(flat):
                record.done = True
                return core.render(record)
            outcome = await core.run(flat[start - 1:], on_error=on_error,
                                     step_delay_ms=step_delay_ms, resume_of=record)
            core.remember(outcome)
            return core.render(outcome)

        if not steps:
            return core.list_runs()
        outcome = await core.run(steps, on_error=on_error, step_delay_ms=step_delay_ms)
    except core.ChainError as exc:
        return f"chain rejected: {exc}"
    core.remember(outcome)
    return core.render(outcome)
