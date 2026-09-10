"""工具输出的统一上限与截断规则。

设计（对齐 opencode / 官方 fetch server / DSH / Codex 的做法）
-----------------------------------------------------------
1. **一次工具结果有软上限**（``SOFT_LIMIT_CHARS``），超了就截断。
2. **截断必须说清楚三件事**：显示到哪、总共多少、**下一步用什么参数继续**。
   干巴巴一句 "truncated" 对 agent 没用 —— 各家（opencode 的
   ``Use offset=1235 to continue.``、官方 fetch 的 ``Call the fetch tool with a
   start_index of N``）都会把续读参数写进文案。
3. **超长单行单独截断**：前端 bundle 压缩成一行 1 MB 是常态，行号翻页对它无效。
4. **内联数据只给摘要**：``data:`` URI 里可能塞着 200 KB+ 的 wasm/base64，
   绝不整段吐给模型。
5. **分页粒度分三种，不要混**：
   - 行号 —— 源码类（``ved_script_source``）
   - 字符 offset —— 文本类（``ved_fetch``）
   - 条数 offset —— 列表类（``ved_apis`` / ``ved_list_scripts`` / ``ved_search`` …）
6. **信息本身有持有**（内存里的捕获记录、DOM 快照、脚本源码，落盘的页面缓存与导出），
   所以默认可以给得小：agent 想细看再调一次，比一次塞满上下文便宜。
7. 配了 ``--response-dir`` 时，被截断的**全量**顺手 spill 到 ``<response-dir>/_spill/``，
   返回里给出路径；没配就只给分页参数（不报错）。

注意：本模块只负责"怎么说"，不负责"取什么"。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from veddata import naming, paths

SOFT_LIMIT_CHARS = 8000        # 一次结果的目标字符上限
MAX_LINE_CHARS = 2000          # 单行上限（同 opencode 的 MAX_LINE_LENGTH）
LIST_LIMIT = 30                # 列表类默认条数
TREE_DEPTH = 2                 # 树类默认深度
VALUE_CHARS = 60               # 单值（cookie / token / header 值）截断
URL_CHARS = 300                # URL 截断
SPILL_DIRNAME = "_spill"
SPILL_KEEP = 32                # spill 目录最多保留几份
ELLIPSIS = "…"


# ---- 单值 / 单行 ----------------------------------------------------------


def clip(text: object, limit: int = VALUE_CHARS) -> str:
    """单值截断（cookie 值、token、header 值这类）。"""
    raw = "" if text is None else str(text)
    return raw if len(raw) <= limit else raw[:limit] + ELLIPSIS


def clip_line(line: str, limit: int = MAX_LINE_CHARS) -> str:
    """单行截断 —— 压缩 JS 一行 1 MB，不截就是刷屏。"""
    if len(line) <= limit:
        return line
    return f"{line[:limit]}{ELLIPSIS} (line truncated to {limit} chars)"


def clip_lines(lines: Iterable[str], limit: int = MAX_LINE_CHARS) -> list[str]:
    return [clip_line(line, limit) for line in lines]


def describe_inline(source: str) -> str:
    """``data:`` URI 只给摘要，绝不吐内容。

    例：``data:application/wasm;base64,AGFzbQ…``（231 KB）→ ``data:(application/wasm, 231536 bytes)``。
    """
    if not source.startswith("data:"):
        return source
    head, _, payload = source.partition(",")
    mime = head[len("data:"):].split(";")[0] or "unknown"
    return f"data:({mime}, {len(payload)} bytes)"


# ---- 分页 / 截断文案 ------------------------------------------------------


def page_footer(
    *,
    shown_from: int,
    shown_to: int,
    total: int,
    param: str = "offset",
    next_value: int | None = None,
    unit: str = "条",
) -> str:
    """统一的页脚文案；能继续时必须给出参数名和值。"""
    if total == 0:
        return f"(共 0 {unit})"
    if next_value is None:
        return f"(显示 {shown_from}-{shown_to} / 共 {total} {unit}，已全部显示)"
    return f"(显示 {shown_from}-{shown_to} / 共 {total} {unit}。用 {param}={next_value} 继续)"


def paginate(
    items: Sequence,
    offset: int = 0,
    limit: int = LIST_LIMIT,
    *,
    unit: str = "条",
    param: str = "offset",
) -> tuple[list, str]:
    """列表分页：返回 ``(本页条目, 页脚文案)``。"""
    total = len(items)
    start = max(0, int(offset or 0))
    size = max(1, int(limit or LIST_LIMIT))
    start = min(start, total)
    chunk = list(items[start:start + size])
    shown_to = start + len(chunk)
    next_value = shown_to if shown_to < total else None
    return chunk, page_footer(
        shown_from=start + 1 if chunk else 0,
        shown_to=shown_to,
        total=total,
        param=param,
        next_value=next_value,
        unit=unit,
    )


def spill(text: str, *, hint: str = "output") -> Path | None:
    """把被截断的全量写到 ``<--response-dir>/_spill/``，返回路径。

    没配置 ``--response-dir`` 就返回 ``None``（不报错 —— spill 是加分项，不是前提）。
    """
    base = paths.response_dir()
    if base is None:
        return None
    try:
        directory = paths.prepare_dir(Path(base) / SPILL_DIRNAME, what="spill 目录")
    except paths.PathError:
        return None

    safe = "".join(c for c in hint if c.isalnum() or c in "-_")[:32] or "output"
    path = naming.unique_path(directory, f"{safe}_{naming.stamp()}", ".txt")
    try:
        path.write_text(text, encoding="utf-8")
        _prune(directory)
    except OSError:
        return None
    return path


def _prune(directory: Path) -> None:
    """spill 目录只保留最近 ``SPILL_KEEP`` 份。"""
    try:
        files = sorted(directory.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for stale in files[SPILL_KEEP:]:
        try:
            stale.unlink()
        except OSError:
            pass


def truncate_text(
    text: str,
    *,
    limit: int = SOFT_LIMIT_CHARS,
    hint: str = "",
    unit: str = "字符",
) -> str:
    """整块文本收口：超上限就截断，并说明"下一步"（可选 spill 全量）。"""
    if len(text) <= limit:
        return text

    lines = [text[:limit], "", f"{ELLIPSIS} (输出超过上限：显示 1-{limit} / 共 {len(text)} {unit}。"]
    spooled = spill(text, hint=hint or "output")
    if spooled is not None:
        lines.append(f"   全量已写入：{spooled}")
    if hint:
        lines.append(f"   {hint}")
    lines.append(")")
    return "\n".join(lines)


def clamp(value: int, *, low: int, high: int, default: int) -> int:
    """把调用方传进来的数字夹到合理区间（0/负数一律回落到默认值）。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number <= 0:
        return default
    return max(low, min(high, number))
