"""下载事实：浏览器在下载什么、下到哪了 —— 只记录、不接管。

原则（仓库既定）：只说事实；**有下载才说，没有就不加**。消息形态：

    download: a.svg → E:\\Downloads\\a.svg (completed, 4.2 KB)
    download: big.zip (in progress, 3.1/4.2 MB) → E:\\Downloads\\big.zip
    download: broken.svg (canceled)

生命周期（用户定的模型）：
- ``inProgress`` **不进队列**：每次调用时实时拉当时的值（拉取即最新）
- ``completed`` / ``canceled`` 进队列：**下一次 MCP 调用带出去，发完即清**（一次性消费）
- 队列按 guid 去重、上限 10 条（很久没有调用也不会堆积）

怎么拿到这些事实：用我们**自己的一条 browser 级 CDP 连接**订阅
``Browser.downloadWillBegin`` / ``Browser.downloadProgress``，并先用
``Browser.setDownloadBehavior(behavior="allow", downloadPath=<下载目录>)`` 把
"存在哪儿"告诉浏览器 —— 目录是从 profile 偏好里读出来的**用户自己的**下载目录，
文件落原处不变，我们只是因此知道完整路径（CDP 事件本身不带路径）。
"""

from __future__ import annotations

import json
from pathlib import Path

MAX_QUEUE = 10

_queue: list[dict] = []          # 结束态（completed / canceled），等下一次调用取走
_active: dict[str, dict] = {}    # 中间态，实时拉
_download_dir: Path | None = None


def _human(size: int) -> str:
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


def download_dir(profile: Path) -> Path:
    """从 profile 偏好里读用户自己的下载目录（读不到就退回 <profile>/downloads）。"""
    profile = Path(profile)
    for candidate in (profile / "Default" / "Preferences", profile / "Preferences"):
        try:
            prefs = json.loads(candidate.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                                       # noqa: BLE001
            continue
        directory = (prefs.get("download") or {}).get("default_directory")
        if directory:
            return Path(directory)
    return profile / "downloads"


def _line(item: dict) -> str:
    name = item.get("filename") or "(unknown name)"
    state = item.get("state") or "inProgress"
    if state == "completed":
        return f"download: {name} → {item.get('path', '?')} (completed, {_human(item.get('length', 0))})"
    if state == "inProgress":
        progress = f"{_human(item.get('received', 0))}/{_human(item.get('length', 0))}"
        return f"download: {name} (in progress, {progress}) → {item.get('path', '?')}"
    return f"download: {name} ({state})"


def render() -> list[str]:
    return [_line(item) for item in _queue] + [_line(item) for item in _active.values()]


def take_lines() -> list[str]:
    """取走"结束态"（一次性）＋ 当前"中间态"（实时）。没有下载就返回空列表。"""
    lines = render()
    _queue.clear()
    return lines


def append_facts(result, separator: str = "\n"):
    """把下载事实附在工具结果末尾；没有下载时原样返回。"""
    if not isinstance(result, str):
        return result
    lines = take_lines()
    if not lines:
        return result
    return f"{result}{separator}{separator.join(lines)}"


# ---------------- CDP 事件 ----------------

def on_will_begin(params: dict) -> None:
    guid = params.get("guid") or ""
    name = params.get("suggestedFilename") or ""
    path = str((_download_dir / name)) if (_download_dir and name) else ""
    _active[guid] = {"guid": guid, "filename": name, "url": params.get("url", ""),
                     "path": path, "state": "inProgress", "received": 0, "length": 0}


def on_progress(params: dict) -> None:
    guid = params.get("guid") or ""
    item = _active.get(guid) or {"guid": guid}
    item["state"] = params.get("state", "inProgress")
    item["received"] = int(params.get("receivedBytes") or 0)
    item["length"] = int(params.get("totalBytes") or 0)
    if item["state"] == "inProgress":
        _active[guid] = item
        return
    _active.pop(guid, None)
    _queue[:] = [old for old in _queue if old.get("guid") != guid]     # guid 去重
    _queue.append(item)
    del _queue[:-MAX_QUEUE]                                           # 只留最近的


async def attach(cdp, profile: Path) -> None:
    """挂事件 + 把下载目录告诉浏览器（目录仍是用户自己的，文件落原处）。"""
    global _download_dir
    _download_dir = download_dir(profile)
    try:
        _download_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    cdp.on("Browser.downloadWillBegin", on_will_begin)
    cdp.on("Browser.downloadProgress", on_progress)
    try:
        await cdp.send("Browser.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": str(_download_dir),
            "eventsEnabled": True,
        })
    except Exception:                                                           # noqa: BLE001
        pass


def reset() -> None:
    """关浏览器时清干净（结束态若还没送出就丢了 —— 由 take_lines 在关闭前带走）。"""
    _queue.clear()
    _active.clear()
    global _download_dir
    _download_dir = None
