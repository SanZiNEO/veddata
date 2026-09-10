"""打 JS 观测点前的"先读后打"策略。

对齐 deepseek-harness 的 ``fs-observation-policy``：**先观测、再变更**。
那边是"编辑文件前必须先读过"，这边是"给脚本打断点前必须先读过源码"。

三层分工（和 DSH 一致）:
1. **账本**（本模块）：按 tab 隔离，记录每个脚本 URL 被 ``ved_script_source``
   读过时的**指纹**（行数 + 内容摘要）。
2. **检查**：``check_read()`` 在打 JS 观测点前查账本 ——
   没读过 → ``WATCH_NOT_READ``；读过但内容变了 → ``WATCH_STALE``；
   脚本不在这个 tab 的注册表里 → ``WATCH_NOT_FOUND``。
3. **文案**：``remediate()`` 把三个码统一成**带恢复动作**的一句话给模型看
   （对齐 DSH 的 ``remediateFsError``）。

为什么指纹而不是"读没读过"这么简单：页面重新加载后同名 URL 的源码可能已经变了，
拿旧认知去打断点等于在错误的行上设断点 —— 所以读过之后内容一变就要重读。

注意：**读到任意窗口即视为已读**（和 DSH 的 read 一样，按文件而非按行记账）。
"""

from __future__ import annotations

import hashlib

WATCH_NOT_READ = "WATCH_NOT_READ"
WATCH_STALE = "WATCH_STALE"
WATCH_NOT_FOUND = "WATCH_NOT_FOUND"


class WatchPolicyError(Exception):
    """打观测点被策略拒绝（携带结构化 code，便于上游路由）。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def fingerprint(source: str) -> str:
    """源码指纹：``<行数>:<sha1 前 8 位>``。"""
    lines = source.count("\n") + 1
    digest = hashlib.sha1(source.encode("utf-8", "ignore")).hexdigest()[:8]
    return f"{lines}:{digest}"


class ObservationLedger:
    """按 tab 隔离的观测账本：``tab_id → {url: 指纹}``。"""

    def __init__(self) -> None:
        self._by_tab: dict[str, dict[str, str]] = {}

    def observe(self, tab_id: str, url: str, source: str) -> None:
        self._by_tab.setdefault(tab_id, {})[url] = fingerprint(source)

    def observed(self, tab_id: str, url: str) -> str | None:
        return self._by_tab.get(tab_id, {}).get(url)

    def forget_tab(self, tab_id: str) -> None:
        self._by_tab.pop(tab_id, None)

    def clear(self) -> None:
        self._by_tab.clear()


_ledger = ObservationLedger()


def ledger() -> ObservationLedger:
    return _ledger


def check_read(tab_id: str, url: str, current_source: str | None) -> None:
    """打 JS 观测点前的检查；不满足就抛 :class:`WatchPolicyError`。

    Args:
        tab_id: 目标 tab。
        url: 脚本 URL。
        current_source: 该脚本**当前**的源码（取不到传 ``None``）。
    """
    if current_source is None:
        raise WatchPolicyError(WATCH_NOT_FOUND, f'script not found in this tab: "{url}"')
    seen = _ledger.observed(tab_id, url)
    if seen is None:
        raise WatchPolicyError(WATCH_NOT_READ, f'watch requires reading "{url}" first')
    if seen != fingerprint(current_source):
        raise WatchPolicyError(WATCH_STALE, f'"{url}" changed since it was read')


def remediate(error: Exception, url: str, line: int) -> str:
    """把策略失败改写成面向模型的、**带恢复动作**的一句话。"""
    code = getattr(error, "code", "")
    if code == WATCH_NOT_READ:
        return (
            f'cannot watch "{url}:{line}": script has not been read — '
            f'call ved_script_source(url="{url}") first, then retry'
        )
    if code == WATCH_STALE:
        return (
            f'cannot watch "{url}:{line}": script changed since it was read — '
            f're-read it with ved_script_source(url="{url}"), then retry'
        )
    if code == WATCH_NOT_FOUND:
        return (
            f'cannot watch "{url}:{line}": script not found in this tab — '
            f'use ved_list_scripts to pick a loaded script'
        )
    return str(error)
