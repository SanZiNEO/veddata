"""状态观测策略：状态变了，就必须先"重新建档"，否则不许动页面。

对齐 deepseek-harness 的 ``fs-observation-policy``（owner→targetKey 观测账本 +
``FS_NOT_OBSERVED`` / ``FS_STALE_VERSION``），和本项目 ``watch_policy.py`` 同一套路子。

为什么需要
----------
浏览器是**共享可变状态**：页面自己会跳走（重定向/自毁）、用户会在窗口里登录、
过验证、开关标签页。AI 手上那份"现在有哪些页、都在哪"随时会过期 ——
拿着旧地图去操作，就是在验证页上瞎点、点到已经变空白的页。

三层分工（与 watch_policy 一致）：
1. **账本**（本模块）：会话级 ``epoch``，记录"AI 最后一次建档是在哪一版状态上"。
2. **检查**：``require()`` 在依赖活状态的工具入口调用 —— 没建档 → ``STATE_NOT_OBSERVED``；
   建过档但之后状态又变了 → ``STATE_STALE``（带上**变了什么**）。
3. **文案**：``remediate()`` 把两个码统一成**带恢复动作**的一句话给模型看。

两条关键设计（避免刷爆 epoch、也避免把自己锁死）
------------------------------------------------
- **工具自己在返回时重新建档**：``ved_goto`` / ``ved_act`` / ``ved_tabs`` / ``ved_status``
  完成动作的同时就把账本推到当前 epoch（它们返回的本来就是最新状态）。
  只有**工具之外发生的变化**（页面自跳、用户手点、弹窗）会留下脏账。
- **只认结构性变化**：标签页增删、主框架 URL 变化、人机门报告。
  DOM 内容变化、hash 变化、SPA 内部跳转都不算。
"""

from __future__ import annotations

import time

STATE_NOT_OBSERVED = "STATE_NOT_OBSERVED"
STATE_STALE = "STATE_STALE"

_MAX_REASONS = 6


class StatePolicyError(Exception):
    """因为"没建档 / 建档过期"被拒绝（携带结构化 code，便于上游路由）。"""

    def __init__(self, code: str, message: str, tool: str = "", reasons: list[str] | None = None):
        super().__init__(message)
        self.code = code
        self.tool = tool
        self.reasons = list(reasons or [])


class EpochLedger:
    """会话级状态账本：``epoch``（当前状态版本） vs ``observed``（AI 看过的版本）。"""

    def __init__(self) -> None:
        self._epoch = 0
        self._observed: int | None = None
        self._reasons: list[str] = []

    # ---- 状态变化 ----

    @property
    def epoch(self) -> int:
        return self._epoch

    def mark_dirty(self, reason: str) -> int:
        """状态变了：epoch +1，并记下变化原因（供拒绝文案使用）。"""
        self._epoch += 1
        if reason and reason not in self._reasons:
            self._reasons.append(reason)
            del self._reasons[:-_MAX_REASONS]
        return self._epoch

    # ---- AI 建档 ----

    def observe(self) -> int:
        """AI 确认过当前状态（调了 ved_status / ved_tabs，或某个工具返回了最新状态）。"""
        self._observed = self._epoch
        self._reasons.clear()
        return self._epoch

    @property
    def observed_epoch(self) -> int | None:
        return self._observed

    @property
    def stale(self) -> bool:
        return self._observed is None or self._observed < self._epoch

    @property
    def reasons(self) -> list[str]:
        return list(self._reasons)

    def reset(self) -> None:
        self._epoch = 0
        self._observed = None
        self._reasons.clear()

    def describe(self) -> str:
        if self._observed is None:
            return f"state epoch={self._epoch}, not observed yet"
        if self._observed < self._epoch:
            return f"state epoch={self._epoch}, observed={self._observed}, changed: {'; '.join(self._reasons) or '-'}"
        return f"state epoch={self._epoch}, observed={self._observed} (fresh)"


_ledger = EpochLedger()


def ledger() -> EpochLedger:
    return _ledger


def mark_dirty(reason: str) -> int:
    return _ledger.mark_dirty(reason)


def observe() -> int:
    return _ledger.observe()


def reset() -> None:
    _ledger.reset()


def require(tool: str) -> None:
    """依赖活状态的工具入口检查；不满足就抛 :class:`StatePolicyError`。

    Args:
        tool: 工具名（写进错误里，便于模型理解是哪一步被拦）。
    """
    if _ledger.observed_epoch is None:
        raise StatePolicyError(
            STATE_NOT_OBSERVED, f"{tool}: browser state has never been observed", tool=tool,
        )
    if _ledger.observed_epoch < _ledger.epoch:
        raise StatePolicyError(
            STATE_STALE, f"{tool}: browser state changed since last observation",
            tool=tool, reasons=_ledger.reasons,
        )


def remediate(error: Exception) -> str:
    """把策略失败改写成面向模型的、**带恢复动作**的一句话。"""
    code = getattr(error, "code", "")
    tool = getattr(error, "tool", "this tool")
    if code == STATE_NOT_OBSERVED:
        return (
            f"cannot run {tool}: browser state has not been looked at yet — "
            f"call ved_status() first (it lists tabs, their URLs and any human-check page), then retry"
        )
    if code == STATE_STALE:
        reasons = "; ".join(getattr(error, "reasons", []) or []) or "page/tab changed"
        return (
            f"cannot run {tool}: browser state changed outside of tool calls ({reasons}) — "
            f"call ved_status() to re-check which tabs exist and what page each is on, then retry"
        )
    return str(error)


def stamp() -> float:
    """给调试用：变更时刻。"""
    return time.time()


def guarded(fn):
    """工具装饰器：**依赖活状态**的工具先过准入检查，被拦时返回恢复文案（不抛异常）。

    用法（注意放在 ``state.mcp.tool()`` **里面**）::

        @state.mcp.tool()
        @guarded
        async def ved_act(...): ...
    """
    import functools

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            require(fn.__name__)
        except StatePolicyError as exc:
            return remediate(exc)
        return await fn(*args, **kwargs)

    return wrapper
