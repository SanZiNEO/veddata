"""scripts.py：Debugger 必须"用到才开"（这是 boss 直聘能活下来的关键）。

背景：以前 ``attach()`` 里直接 ``Debugger.enable`` —— 等于每个页面都被挂上调试器，
站点自检一眼看见就自毁。DrissionPage / 裸 CDP 客户端都是按需 enable。
"""

from __future__ import annotations

import asyncio

from veddata.scripts import ScriptRegistry


class FakeCdp:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.handlers: dict = {}

    def on(self, event: str, handler) -> None:
        self.handlers[event] = handler

    async def send(self, method: str, params=None):
        self.sent.append(method)
        if method == "Debugger.getScriptSource":
            return {"scriptSource": "// fixture"}
        return {}


def test_attach_only_listens_and_does_not_enable_debugger():
    cdp = FakeCdp()
    registry = ScriptRegistry(None, cdp)
    asyncio.run(registry.attach(cdp))
    assert cdp.sent == [], "attach 阶段不应该发任何 CDP 命令"
    assert "Debugger.scriptParsed" in cdp.handlers


def test_get_source_enables_debugger_on_demand_and_only_once():
    cdp = FakeCdp()
    registry = ScriptRegistry(None, cdp)
    asyncio.run(registry.attach(cdp))
    registry._scripts["https://a/app.js"] = {"script_id": "7", "length": 10, "start_line": 0}

    source = asyncio.run(registry.get_source("https://a/app.js"))
    assert source == "// fixture"
    assert cdp.sent.count("Debugger.enable") == 1

    # 幂等：第二次读（走缓存）不再重复开
    assert asyncio.run(registry.get_source("https://a/app.js")) == "// fixture"
    assert cdp.sent.count("Debugger.enable") == 1


def test_enable_is_idempotent_without_cdp():
    registry = ScriptRegistry(None, None)
    asyncio.run(registry.enable())                       # 没 cdp 也不能炸
    assert registry._enabled is False
