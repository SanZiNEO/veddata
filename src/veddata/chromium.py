"""Chromium 启动 / 接管 —— 自起普通 Chrome + CDP 端口（DrissionPage 式）。

为什么不用 Playwright 启动浏览器
--------------------------------
Playwright 用 ``--remote-debugging-pipe``，并附加它自己一长串启动开关；实测同一份
``chrome.exe``：pipe → ``navigator.webdriver=true``（boss 直聘据此自毁页面）；
自起 Chrome + ``--remote-debugging-port`` → ``webdriver=false``、无注入痕迹、正常 UA。

三条实用设计
------------
1. **profile 里记端口与 pid**（``.veddata-browser.json``）：重连时先看已有实例是否还活着，
   活着就复用 —— MCP 服务重启、用户登录/过验证之后会话都不丢。
2. **生命周期归自己管**：我们起的、以及档案里记着 pid 的那个，``close_running`` 能真关掉；
   只有 ``BROWSER_ADDRESS`` 指定的外部浏览器才只断开。
3. **启动失败不重试**：profile 被另一个 Chrome 占用时，多试一次就是多开一个窗口 ——
   只起一次，失败就把事实（pid / 端口 / 退出码 / profile 路径）报出来。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PORT_FILE = ".veddata-browser.json"
_READY_TIMEOUT = 25.0
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class ChromiumError(RuntimeError):
    """起不来 / 找不到浏览器 / profile 被占用。"""


def free_port() -> int:
    """要一个当前空闲的本地端口（绑定后立刻释放，Chrome 起来前有极小竞态）。"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def build_args(path: str, port: int, profile: Path, headless: bool) -> list[str]:
    """自起 Chrome 的参数：**只要最少的**，绝不带自动化开关。"""
    args = [
        path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if headless:
        args.append("--headless=new")
    return args


# ---------------- 浏览器可执行文件查找 ----------------

_WIN_CHROME_RELATIVE = [
    ("LOCALAPPDATA", r"Google\Chrome\Application\chrome.exe"),
    ("ProgramFiles", r"Google\Chrome\Application\chrome.exe"),
    ("ProgramFiles(x86)", r"Google\Chrome\Application\chrome.exe"),
]
_WIN_EDGE_RELATIVE = [
    ("ProgramFiles(x86)", r"Microsoft\Edge\Application\msedge.exe"),
    ("ProgramFiles", r"Microsoft\Edge\Application\msedge.exe"),
    ("LOCALAPPDATA", r"Microsoft\Edge\Application\msedge.exe"),
]
_WIN_REGISTRY = [
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
]
_WIN_REGISTRY_EDGE = [
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
]


def _from_registry(keys: list[str]) -> str | None:
    if sys.platform != "win32":
        return None
    try:
        from winreg import HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE, OpenKey, QueryValueEx
    except ImportError:                                                        # pragma: no cover
        return None
    for root in (HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER):
        for key in keys:
            try:
                with OpenKey(root, key) as handle:
                    value, _ = QueryValueEx(handle, None)
                if value and Path(value).exists():
                    return str(value)
            except OSError:
                continue
    return None


def _from_relative(entries: list[tuple[str, str]]) -> str | None:
    for env_name, tail in entries:
        base = os.environ.get(env_name)
        if not base:
            continue
        candidate = Path(base) / tail
        if candidate.exists():
            return str(candidate)
    return None


def _from_path(names: list[str]) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        for name in names:
            candidate = Path(directory) / name
            if candidate.exists():
                return str(candidate)
    return None


def find_chrome() -> str | None:
    if sys.platform == "darwin":
        for candidate in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                          "/Applications/Chromium.app/Contents/MacOS/Chromium"):
            if Path(candidate).exists():
                return candidate
    return (_from_registry(_WIN_REGISTRY) or _from_relative(_WIN_CHROME_RELATIVE)
            or _from_path(["chrome.exe" if sys.platform == "win32" else "google-chrome",
                           "chrome", "chromium"]))


def find_edge() -> str | None:
    if sys.platform == "darwin":
        candidate = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
        return candidate if Path(candidate).exists() else None
    return (_from_registry(_WIN_REGISTRY_EDGE) or _from_relative(_WIN_EDGE_RELATIVE)
            or _from_path(["msedge.exe" if sys.platform == "win32" else "microsoft-edge"]))


def browser_path() -> str | None:
    """按 ``BROWSER_PATH`` 决定用哪个浏览器（空/未知 → Chrome 优先，其次 Edge）。"""
    raw = os.environ.get("BROWSER_PATH", "").strip()
    if raw:
        lowered = raw.lower()
        if lowered in ("edge", "msedge"):
            return find_edge()
        if lowered not in ("chrome", "chrome.exe", "google-chrome"):
            candidate = Path(raw).expanduser()
            if candidate.exists():
                return str(candidate)
    return find_chrome() or find_edge()


# ---------------- 存活判定 / 端口档案 ----------------

def alive(port: int, timeout: float = 1.5) -> bool:
    """CDP 端点是否响应（``/json/version``）。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        return bool(payload.get("webSocketDebuggerUrl"))
    except Exception:                                                           # noqa: BLE001
        return False


def _read_port_payload(profile: Path) -> dict:
    try:
        return json.loads((Path(profile) / PORT_FILE).read_text(encoding="utf-8"))
    except Exception:                                                           # noqa: BLE001
        return {}


def read_port_file(profile: Path) -> int | None:
    try:
        return int(_read_port_payload(profile)["port"])
    except Exception:                                                           # noqa: BLE001
        return None


def read_pid(profile: Path) -> int:
    """档案里记的浏览器主进程 pid（没有就是 0）。"""
    try:
        return int(_read_port_payload(profile).get("pid") or 0)
    except Exception:                                                           # noqa: BLE001
        return 0


def write_port_file(profile: Path, port: int, pid: int | None = None) -> None:
    target = Path(profile) / PORT_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"port": port, "pid": pid}, ensure_ascii=False), encoding="utf-8")


def clear_port_file(profile: Path) -> None:
    try:
        (Path(profile) / PORT_FILE).unlink()
    except OSError:
        pass


def kill_tree(pid: int) -> bool:
    """按 pid 结束整个进程树（Windows: taskkill /T /F）。返回是否成功。"""
    if not pid:
        return False
    try:
        if sys.platform == "win32":
            done = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                  capture_output=True, text=True)
        else:
            done = subprocess.run(["kill", "-TERM", f"-{pid}"], capture_output=True, text=True)
        return done.returncode == 0
    except Exception:                                                           # noqa: BLE001
        return False


def close_running(profile: Path) -> dict:
    """关掉档案里记的那个浏览器（**哪怕它不是我起起的**）。

    Returns:
        ``{"port":…, "pid":…, "killed":bool}`` —— 只有事实，调用方照原样报告。
    """
    profile = Path(profile)
    port = read_port_file(profile)
    pid = read_pid(profile)
    killed = kill_tree(pid)
    clear_port_file(profile)
    return {"port": port, "pid": pid, "killed": killed}


# ---------------- 启动器 ----------------

class Launcher:
    """确保"有一个跑着的普通 Chrome 可以用"，返回它的 CDP 地址。"""

    def __init__(self, path: str | None = None) -> None:
        self.path = path or browser_path()
        self.process: subprocess.Popen | None = None
        self.port: int | None = None
        self.started = False

    def ensure(self, profile: Path, headless: bool) -> str:
        """返回 ``http://127.0.0.1:<port>``；能复用已有实例就复用。

        Raises:
            ChromiumError: 找不到浏览器，或起不来（**只尝试一次**，不重试 —— 重试只会多开窗口）。
        """
        profile = Path(profile)
        profile.mkdir(parents=True, exist_ok=True)

        existing = read_port_file(profile)
        if existing and alive(existing):
            self.port = existing
            self.started = False
            return f"http://127.0.0.1:{existing}"

        if not self.path:
            raise ChromiumError(
                "未找到 Chrome/Edge：请安装，或用 BROWSER_PATH 指定浏览器可执行文件"
            )

        port = free_port()
        args = build_args(self.path, port, profile, headless)
        try:
            process = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL,
                                       creationflags=_CREATE_NO_WINDOW)
        except OSError as exc:
            raise ChromiumError(f"无法启动 {self.path}：{exc}") from exc

        if self._wait_ready(port, process):
            self.process = process
            self.port = port
            self.started = True
            write_port_file(profile, port, process.pid)
            return f"http://127.0.0.1:{port}"

        code = process.poll()
        self._terminate(process)
        raise ChromiumError(
            f"Chrome 未能就绪（pid={process.pid}, port={port}, 退出码={code}）—— "
            f"profile 可能已被另一个 Chrome 占用：{profile}"
        )

    def stop(self, profile: Path | None = None, clear: bool = True) -> None:
        """关掉**本进程起的**实例；接管来的不动。

        Args:
            profile: 档案所在的 profile 目录。
            clear: 是否删掉端口档案。**detach（只断开）时必须传 False** ——
                   删了就等于把"我们在用的那个浏览器"弄丢，下次会去起一个新的（profile 被占用→开一堆窗口）。
        """
        if self.started and self.process is not None:
            self._terminate(self.process)
            self.process = None
            self.started = False
        if profile is not None and clear:
            clear_port_file(Path(profile))

    @staticmethod
    def _wait_ready(port: int, process: subprocess.Popen, timeout: float = _READY_TIMEOUT) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if alive(port):
                return True
            if process.poll() is not None:          # 进程自己退了，别傻等
                return False
            time.sleep(0.25)
        return False

    @staticmethod
    def _terminate(process: subprocess.Popen) -> None:
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:                                                       # noqa: BLE001
            try:
                process.kill()
            except Exception:                                                   # noqa: BLE001
                pass
