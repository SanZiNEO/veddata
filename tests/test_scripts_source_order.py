"""scripts.py：读源码的顺序 —— 先网络直取（不挂调试器），拿不到才开 Debugger。

前提（用户要求）：**监测点功能不受影响** —— JS 观测点由 watch_engine 自己
``Debugger.enable``，与这里无关（见 tests 里对 watch_engine 的断言）。
"""

from __future__ import annotations

import asyncio

from veddata.scripts import ScriptRegistry
from veddata import watch_engine


class FakeResponse:
    def __init__(self, ok: bool = True, text: str = "// from network") -> None:
        self.ok = ok
        self._text = text

    async def text(self) -> str:
        return self._text


class FakePage:
    """只实现 get_source 用到的那一点：page.request.get(url) → Response。"""

    def __init__(self, ok: bool = True, boom: bool = False) -> None:
        self.request = self
        self._ok = ok
        self._boom = boom

    async def get(self, url: str):
        if self._boom:
            raise RuntimeError("network down")
        return FakeResponse(self._ok, f"// {url}")


class FakeCdp:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def on(self, event: str, handler) -> None:
        pass

    async def send(self, method: str, params=None):
        self.sent.append(method)
        if method == "Debugger.getScriptSource":
            return {"scriptSource": "// from runtime"}
        return {}


def test_network_fetch_is_preferred_and_keeps_debugger_off():
    cdp = FakeCdp()
    registry = ScriptRegistry(FakePage(), cdp)
    registry._scripts["https://a/app.js"] = {"script_id": "1", "length": 9, "start_line": 0}

    source = asyncio.run(registry.get_source("https://a/app.js"))
    assert source == "// https://a/app.js"
    assert "Debugger.enable" not in cdp.sent, "网络能拿到源码时不该挂调试器"


def test_falls_back_to_runtime_when_network_fails():
    cdp = FakeCdp()
    registry = ScriptRegistry(FakePage(boom=True), cdp)
    registry._scripts["https://a/app.js"] = {"script_id": "1", "length": 9, "start_line": 0}

    source = asyncio.run(registry.get_source("https://a/app.js"))
    assert source == "// from runtime"
    assert "Debugger.enable" in cdp.sent


def test_inline_script_goes_straight_to_runtime():
    cdp = FakeCdp()
    registry = ScriptRegistry(FakePage(), cdp)
    registry._scripts["data:text/javascript,var a=1"] = {"script_id": "9", "length": 9, "start_line": 0}

    source = asyncio.run(registry.get_source("data:text/javascript,var a=1"))
    assert source == "// from runtime"
    assert "Debugger.enable" in cdp.sent


def test_cache_avoids_second_fetch():
    cdp = FakeCdp()
    registry = ScriptRegistry(FakePage(), cdp)
    registry._scripts["https://a/app.js"] = {"script_id": "1", "length": 9, "start_line": 0}
    first = asyncio.run(registry.get_source("https://a/app.js"))
    cdp.sent.clear()
    second = asyncio.run(registry.get_source("https://a/app.js"))
    assert first == second and cdp.sent == []


def test_watch_engine_enables_debugger_itself():
    """监测点自带 Debugger.enable —— 不依赖脚本注册表（用户要求：监测点不受影响）。"""
    import inspect

    source = inspect.getsource(watch_engine)
    assert "Debugger.enable" in source
