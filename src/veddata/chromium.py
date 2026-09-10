"""Chromium 启动 / 接管 —— 自起普通 Chrome + CDP 端口（DrissionPage 式）。

为什么不用 Playwright 启动浏览器
--------------------------------
Playwright 用 ``--remote-debugging-pipe`` 连接，并且**由它决定**一长串启动开关
（``--disable-features=…``、``--disable-infobars``、``--use-mock-keychain``、
``--disable-sync`` …）。实测同一份 ``chrome.exe``（Chrome 152）：

============================  ==================================  ===================
启动方式                       页面上能看到的                       结果
============================  ==================================  ===================
Playwright 默认（自带 Chromium） ``chrome-headless-shell``、无 ``window.chrome``  boss 直聘自毁页面
Playwright ``channel=chrome``  ``--remote-debugging-pipe`` → ``webdriver=true``  同上
Playwright + 去 automation      同上（该开关与 webdriver 无关）      同上
**自起 Chrome + CDP 端口**      ``webdriver=false``、无注入痕迹、真 UA  页面完好
============================  ==================================  ===================

所以：**我们自己 Popen 一个普通 Chrome**，只给调试端口和 profile；Playwright 通过
``connect_over_cdp`` 当纯 CDP 客户端 —— 异步 API、CDP session、init script 全部保留。

三条实用设计
------------
1. **profile 里记端口**（``.veddata-browser.json``）：重连时先看已有实例是否还活着，
   活着就复用。这样 MCP 服务重启、或用户在窗口里登录/过完验证之后，会话不会丢。
2. **生命周归自己管**：我们起的浏览器由我们关（``stop()``）；接管别人的只断开。
3. **找不到 Chrome 不硬失败**：交给上层回退到 Playwright 启动（那时只能接受指纹）。
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
_START_ATTEMPTS = 4
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class ChromiumError(RuntimeError):
    """起不来 / 找不到浏览器。"""


def free_port() -> int:
    """要一个当前空闲的本地端口（绑定后立刻释放，Chrome 起来前有极小竞态）。"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def build_args(path: str, port: int, profile: Path, headless: bool) -> list[str]:
    """自起 Chrome 的参数：**只要最少的**，绝不带自动化开关。

    Args:
        path: 浏览器可执行文件。
        port: CDP 调试端口。
        profile: user-data-dir（持久 profile）。
        headless: ``True`` → 新式无头。

    Returns:
        完整命令行列表（第一项是可执行文件）。
    """
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
    """系统里的 Chrome（注册表 → 常见路径 → PATH）。"""
    if sys.platform == "darwin":
        for candidate in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                          "/Applications/Chromium.app/Contents/MacOS/Chromium"):
            if Path(candidate).exists():
                return candidate
    return (_from_registry(_WIN_REGISTRY) or _from_relative(_WIN_CHROME_RELATIVE)
            or _from_path(["chrome.exe" if sys.platform == "win32" else "google-chrome",
                           "chrome", "chromium"]))


def find_edge() -> str | None:
    """系统里的 Edge（Chrome 的替补）。"""
    if sys.platform == "darwin":
        candidate = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
        return candidate if Path(candidate).exists() else None
    return (_from_registry(_WIN_REGISTRY_EDGE) or _from_relative(_WIN_EDGE_RELATIVE)
            or _from_path(["msedge.exe" if sys.platform == "win32" else "microsoft-edge"]))


def browser_path() -> str | None:
    """按 ``BROWSER_PATH`` 决定用哪个浏览器。

    ``BROWSER_PATH`` 取值：
      - 空 → 自动：Chrome → Edge
      - ``edge`` / ``msedge`` → 只用 Edge
      - 绝对/相对路径 → 用这个可执行文件
      - 其它（``chrome`` 等）→ 当自动处理
    """
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


def read_port_file(profile: Path) -> int | None:
    try:
        payload = json.loads((Path(profile) / PORT_FILE).read_text(encoding="utf-8"))
        return int(payload["port"])
    except Exception:                                                           # noqa: BLE001
        return None


def write_port_file(profile: Path, port: int, pid: int | None = None) -> None:
    target = Path(profile) / PORT_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"port": port, "pid": pid}, ensure_ascii=False), encoding="utf-8")


def clear_port_file(profile: Path) -> None:
    try:
        (Path(profile) / PORT_FILE).unlink()
    except OSError:
        pass


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
            ChromiumError: 找不到浏览器，或连续几次都起不来（常见于 profile 被占用）。
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

        last_error = ""
        for _ in range(_START_ATTEMPTS):
            port = free_port()
            args = build_args(self.path, port, profile, headless)
            try:
                process = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL,
                                           creationflags=_CREATE_NO_WINDOW)
            except OSError as exc:
                last_error = f"无法启动 {self.path}：{exc}"
                continue

            if self._wait_ready(port, process):
                self.process = process
                self.port = port
                self.started = True
                write_port_file(profile, port, process.pid)
                return f"http://127.0.0.1:{port}"

            code = process.poll()
            self._terminate(process)
            last_error = (f"Chrome 未在 {_READY_TIMEOUT:.0f}s 内就绪"
                          f"（退出码 {code}）—— profile 可能已被另一个 Chrome 占用：{profile}"
                          if code is not None else f"Chrome 未在 {_READY_TIMEOUT:.0f}s 内就绪")
        raise ChromiumError(last_error or "Chrome 启动失败")

    def stop(self, profile: Path | None = None) -> None:
        """只关我们自己起的实例；接管来的不动。"""
        if self.started and self.process is not None:
            self._terminate(self.process)
            self.process = None
            self.started = False
        if profile is not None:
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
