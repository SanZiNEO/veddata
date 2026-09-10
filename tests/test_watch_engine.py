"""WatchEngine 测试 —— 用假 page/cdp 锁死观测点的管理与边界。

不需要真浏览器：route / 断点 / resume 全用假对象替换。锁死的不变量：

1. 观测点 id 自动分配、单调递增、不复用；
2. 达到 ``max_hits`` 后**自动移除该点**（热点行不会一直被中断）；
3. 单点 / 总量快照上限（防止内存无界增长）；
4. 删除观测点会连带删掉它的快照；
5. 注册新点后"全部命中"事件必须重新等待（不能复用已 set 的旧事件）；
6. 行号对外 **1-based**，内部转成 CDP 的 0-based。
"""

import asyncio

import pytest

from veddata import watch_engine
from veddata.watch_engine import MAX_PER_WATCH, WatchEngine

# anyio 自带的 pytest 插件（随 fastmcp 一起装上），不需要额外的 pytest-asyncio
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeRequest:
    url = "https://api.example.com/v1/list?page=1"
    method = "GET"
    headers = {":authority": "api.example.com", "accept": "application/json", "cookie": "a=b"}


class FakeRoute:
    def __init__(self):
        self.request = FakeRequest()
        self.continued = False

    async def continue_(self):
        self.continued = True


class FakePage:
    def __init__(self):
        self.routes = {}
        self.unrouted = []

    async def route(self, pattern, handler):
        self.routes[pattern] = handler

    async def unroute(self, pattern):
        self.unrouted.append(pattern)
        self.routes.pop(pattern, None)


class FakeCdp:
    def __init__(self):
        self.sent = []
        self.handlers = {}

    def on(self, event, callback):
        self.handlers[event] = callback

    async def send(self, method, params=None):
        params = params or {}
        self.sent.append((method, params))
        if method == "Debugger.setBreakpointByUrl":
            return {"breakpointId": f"1:{params['lineNumber']}:0:{params['url']}"}
        if method == "Runtime.getProperties":
            return {
                "result": [
                    {"name": "this", "value": {"value": "x"}},
                    {"name": "userid", "value": {"value": 42}},
                    {"name": "secret", "value": {"description": "String"}},
                ]
            }
        return {}

    def methods(self):
        return [m for m, _ in self.sent]


@pytest.fixture()
def engine():
    return WatchEngine(FakePage(), FakeCdp(), None)


async def _drain():
    """让 create_task 派生的收尾任务跑完。"""
    for _ in range(3):
        await asyncio.sleep(0)


# ---- id 与列表 ------------------------------------------------------------


def test_ids_are_unique_and_monotonic(engine):
    assert [engine.alloc_id() for _ in range(3)] == ["w1", "w2", "w3"]


async def test_list_watches_shows_state_and_hint(engine):
    await engine.add_request_watch("/api/*", "r1", max_hits=0)
    out = engine.list_watches()
    assert "r1" in out and "request" in out and "watching" in out
    assert "删除" in out

    await engine.add_request_watch("/api/*", "r2", max_hits=3)
    assert "hits=0/3" in engine.list_watches()


# ---- 请求观测点 -----------------------------------------------------------


async def test_request_watch_records_drops_pseudo_headers_and_continues(engine):
    await engine.add_request_watch("/api/*", "r1", max_hits=1)
    route = FakeRoute()
    await engine._page.routes["/api/*"](route)

    assert route.continued is True, "请求必须放行"
    snapshot = engine._snapshots[0]
    assert snapshot["watch_id"] == "r1" and snapshot["type"] == "request"
    assert ":authority" not in snapshot["headers"], "HTTP/2 伪头不该进快照"


async def test_max_hits_retires_the_watch(engine):
    await engine.add_request_watch("/api/*", "r1", max_hits=2)
    handler = engine._page.routes["/api/*"]
    for _ in range(2):
        await handler(FakeRoute())
    await _drain()

    assert engine._watches["r1"]["state"] == "done"
    assert engine._page.unrouted == ["/api/*"], "达到 max 后必须 unroute"
    assert engine.snapshot_count() == 2


async def test_per_watch_snapshot_cap(engine):
    await engine.add_request_watch("/api/*", "r1", max_hits=0)   # 0 = 不限
    handler = engine._page.routes["/api/*"]
    for _ in range(MAX_PER_WATCH + 5):
        await handler(FakeRoute())
    await _drain()

    assert engine.snapshot_count() == MAX_PER_WATCH, "单点快照必须有上限"


async def test_total_snapshot_cap(engine, monkeypatch):
    monkeypatch.setattr(watch_engine, "MAX_PER_WATCH", 50)
    monkeypatch.setattr(watch_engine, "MAX_TOTAL", 5)

    await engine.add_request_watch("/api/*", "r1", max_hits=0)
    handler = engine._page.routes["/api/*"]
    for _ in range(8):
        await handler(FakeRoute())
    await _drain()

    assert engine.snapshot_count() == 5, "总量上限兜底"


# ---- JS 观测点 ------------------------------------------------------------


async def test_js_watch_line_is_converted_to_zero_based(engine):
    await engine.add_js_watch("https://x/app.js", 148, ["userid"], "j1", max_hits=1)
    bp = [p for m, p in engine._cdp.sent if m == "Debugger.setBreakpointByUrl"][0]
    assert bp["lineNumber"] == 147, "对外 1-based → CDP 0-based"


async def test_paused_event_snapshots_only_asked_variables_and_resumes(engine):
    await engine.add_js_watch("https://x/app.js", 148, ["userid"], "j1", max_hits=1)
    await engine.on_debugger_paused({
        "hitBreakpoints": ["1:147:0:https://x/app.js"],
        "callFrames": [{
            "url": "https://x/app.js",
            "lineNumber": 147,
            "functionName": "load",
            "scopeChain": [{"type": "local", "object": {"objectId": "1"}}],
        }],
    })

    snapshot = engine._snapshots[-1]
    assert snapshot["variables"] == {"userid": 42}, "只快照点名的变量"
    assert snapshot["line"] == 148, "对外报 1-based"
    assert snapshot["call_stack"] == ["load @ https://x/app.js:148"]
    assert "Debugger.resume" in engine._cdp.methods(), "必须自动放行"


async def test_paused_event_without_matching_breakpoint_just_resumes(engine):
    await engine.on_debugger_paused({"hitBreakpoints": ["unknown"], "callFrames": []})
    assert engine.snapshot_count() == 0
    assert "Debugger.resume" in engine._cdp.methods()


# ---- 删除 / 清理 ----------------------------------------------------------


async def test_remove_drops_watch_and_its_snapshots(engine):
    await engine.add_request_watch("/a", "r1", max_hits=0)
    await engine._page.routes["/a"](FakeRoute())
    assert engine.snapshot_count() == 1

    assert await engine.remove("r1") is True
    assert engine.watch_ids() == []
    assert engine.snapshot_count() == 0
    assert engine._page.unrouted == ["/a"]
    assert await engine.remove("nope") is False


async def test_clear_detaches_everything(engine):
    await engine.add_request_watch("/a", "r1", max_hits=0)
    await engine.add_js_watch("https://x/app.js", 5, [], "j1", max_hits=0)

    await engine.clear()
    assert engine.watch_ids() == [] and engine.snapshot_count() == 0
    assert engine._page.unrouted == ["/a"]
    assert "Debugger.removeBreakpoint" in engine._cdp.methods()


# ---- 等待语义 -------------------------------------------------------------


async def test_new_watch_resets_the_done_event(engine):
    await engine.add_request_watch("/a", "r1", max_hits=1)
    await engine._page.routes["/a"](FakeRoute())
    await _drain()
    assert engine._done_event.is_set()

    await engine.add_request_watch("/b", "r2", max_hits=1)
    assert not engine._done_event.is_set(), "新点注册后必须重新等待，不能复用旧事件"


async def test_wait_for_snapshots_times_out_without_hits(engine):
    await engine.add_request_watch("/never", "r1", max_hits=1)
    snapshots = await engine.wait_for_snapshots(timeout=0.05)
    assert snapshots == []
    assert engine.pending_count() == 1
