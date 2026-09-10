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
import os
import sys
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


def _xdg_downloads() -> Path | None:
    """Linux: ``~/.config/user-dirs.dirs`` 里的 ``XDG_DOWNLOAD_DIR``。"""
    base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    try:
        for line in (base / "user-dirs.dirs").read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line.startswith("XDG_DOWNLOAD_DIR="):
                continue
            value = line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(Path.home()))
            path = Path(value)
            if path.exists():
                return path
    except Exception:                                                           # noqa: BLE001
        pass
    return None


def os_downloads_dir() -> Path | None:
    """操作系统自己的"下载"文件夹；拿不到返回 None（**不猜**）。"""
    if sys.platform == "win32":
        try:
            from winreg import HKEY_CURRENT_USER, OpenKey, QueryValueEx

            with OpenKey(HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as key:
                value, _ = QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
            path = Path(str(value).replace("%USERPROFILE%", os.path.expanduser("~")))
            if path.exists():
                return path
        except Exception:                                                       # noqa: BLE001
            pass
    elif sys.platform != "darwin":
        xdg = _xdg_downloads()
        if xdg is not None:
            return xdg
    candidate = Path.home() / "Downloads"
    return candidate if candidate.exists() else None


def download_dir(profile: Path) -> Path | None:
    """用户自己的下载目录：先看 profile 偏好，再看系统"下载"文件夹。

    **拿不到就返回 None** —— 这时绝不猜、也绝不设 downloadPath，
    让浏览器按它自己的行为落盘（我们只报文件名与状态，不挪文件）。
    偏好里若开着"每次询问保存位置"（``prompt_for_download``），同样返回 None ——
    路径是用户每次现选的，我们不许替他做选择。
    """
    profile = Path(profile)
    for candidate in (profile / "Default" / "Preferences", profile / "Preferences"):
        try:
            prefs = json.loads(candidate.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                                       # noqa: BLE001
            continue
        download = prefs.get("download") or {}
        if download.get("prompt_for_download"):
            return None
        directory = download.get("default_directory")
        if directory:
            return Path(directory)
    return os_downloads_dir()


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
    _download_dir = download_dir(profile)        # None = 拿不到用户目录，绝不猜
    if _download_dir is not None:
        try:
            _download_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            _download_dir = None
    cdp.on("Browser.downloadWillBegin", on_will_begin)
    cdp.on("Browser.downloadProgress", on_progress)
    # 目录已知 → allow + downloadPath：文件仍落在原处，我们因此知道完整路径；
    # 目录未知 → default：让浏览器按自己的行为落盘，我们只报文件名与状态（不挪文件）。
    params: dict = {"eventsEnabled": True}
    if _download_dir is not None:
        params["behavior"] = "allow"
        params["downloadPath"] = str(_download_dir)
    else:
        params["behavior"] = "default"
    try:
        await cdp.send("Browser.setDownloadBehavior", params)
    except Exception:                                                           # noqa: BLE001
        pass


def reset() -> None:
    """关浏览器时清干净（结束态若还没送出就丢了 —— 由 take_lines 在关闭前带走）。"""
    _queue.clear()
    _active.clear()
    global _download_dir
    _download_dir = None
