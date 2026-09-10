"""chain.py 核心逻辑测试（不需要浏览器：工具调用用注入的假 caller）。"""

from __future__ import annotations

import asyncio
import time

import pytest

from veddata import observation, state
from veddata.tools import chain as core


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch):
    observation.reset()
    monkeypatch.setattr(state, "_browser", None, raising=False)
    monkeypatch.setattr(state, "_api_pool", None, raising=False)
    observation.observe()      # 默认当作已建档；要测 stale 的用例自己 mark_dirty
    yield
    observation.reset()


class FakeBrowser:
    def __init__(self) -> None:
        self.tab_id = "TAB00001"

    def current_tab_id(self) -> str:
        return self.tab_id

    async def get_current_page(self):
        return None                      # → 跳过人机门检测（本测试不涉及）


class FakePool:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def get_by_tab(self, tab_id: str) -> list[dict]:
        return list(self.records)

    def add(self, url: str) -> None:
        self.records.append({"url": url, "method": "GET"})


def install_browser(pool: FakePool) -> None:
    state._browser = FakeBrowser()
    state.set_pool(pool)


def test_expand_keeps_order_and_expands_repeat():
    steps = [
        {"tool": "ved_open"},
        {"tool": "ved_act", "args": {"action": "click", "target": "下一页"}},
        {"wait": {"ms": 10}},
        {"repeat": {"times": 2, "steps": [{"tool": "ved_apis"}]}},
    ]
    flat = core.expand(steps)
    assert [s.get("tool") or "wait" for s in flat] == ["ved_open", "ved_act", "wait", "ved_apis", "ved_apis"]
    assert flat[3]["_round"] == 1 and flat[4]["_round"] == 2


def test_expand_rejects_disallowed_tools_and_nested_repeat():
    for bad in ({"tool": "ved_close"}, {"tool": "ved_chain"}, {"tool": "rm -rf"}):
        with pytest.raises(core.ChainError):
            core.expand([bad])
    with pytest.raises(core.ChainError):
        core.expand([{"repeat": {"times": 1, "steps": [{"repeat": {"times": 1, "steps": []}}]}}])


def test_run_calls_tools_in_order_and_reports():
    calls: list[str] = []

    async def caller(name, **kwargs):
        calls.append(name)
        return f"{name} ok"

    record = asyncio.run(core.run([{"tool": "ved_open"},
                                  {"tool": "ved_apis"},
                                  {"tool": "ved_act", "args": {"action": "click"}}],
                                  caller=caller))
    assert calls == ["ved_open", "ved_apis", "ved_act"]
    assert record.done and len(record.results) == 3
    assert "chain " + record.id in core.render(record)


def test_step_delay_is_honoured():
    async def caller(name, **kwargs):
        return "ok"

    started = time.time()
    asyncio.run(core.run([{"tool": "ved_open"}, {"tool": "ved_open"}],
                         step_delay_ms=200, caller=caller))
    assert time.time() - started >= 0.2


def test_wait_ms():
    async def caller(name, **kwargs):
        return "ok"

    started = time.time()
    asyncio.run(core.run([{"wait": {"ms": 150}}], caller=caller))
    assert time.time() - started >= 0.15


def test_failure_stops_and_offers_resume():
    async def caller(name, **kwargs):
        if name == "ved_act":
            raise RuntimeError("boom")
        return "ok"

    record = asyncio.run(core.run([{"tool": "ved_open"}, {"tool": "ved_act"}], caller=caller))
    assert not record.done and record.stop_index == 2
    report = core.render(record)
    assert "stopped at step 2" in report
    assert "resume" not in report and "续跑" not in report      # 只陈述事实，不给建议动作


def test_on_error_continue_keeps_going():
    async def caller(name, **kwargs):
        if name == "ved_act":
            raise RuntimeError("boom")
        return "ok"

    record = asyncio.run(core.run([{"tool": "ved_act"}, {"tool": "ved_apis"}],
                                  on_error="continue", caller=caller))
    assert [r.ok for r in record.results] == [False, True]


def test_diff_gives_causality_for_page_touching_steps():
    pool = FakePool()
    install_browser(pool)

    async def caller(name, **kwargs):
        if name == "ved_act":
            pool.add("https://a.com/wapi/zpgeek/search/joblist.json?page=2")
            pool.add("https://a.com/wapi/zpgeek/search/joblist.json?page=2")
            pool.add("https://a.com/wapi/zpcommon/track/report")
        return "clicked"

    record = asyncio.run(core.run([{"tool": "ved_act", "args": {"action": "click"}}], caller=caller))
    diff = record.results[0].diff
    assert diff and "+3 requests" in diff[0]
    assert "joblist ×2" in diff[0] or "joblist" in diff[0]


def test_out_of_band_change_stops_the_chain():
    install_browser(FakePool())
    observation.observe()
    observation.mark_dirty("页面跳转 → https://x/verify")

    async def caller(name, **kwargs):
        return "ok"

    record = asyncio.run(core.run([{"tool": "ved_act", "args": {"action": "click"}}], caller=caller))
    assert not record.done and "outside the chain" in record.stop_reason


def test_max_steps_guard():
    too_many = [{"tool": "ved_apis"}] * 31
    with pytest.raises(core.ChainError):
        asyncio.run(core.run(too_many, caller=lambda *a, **k: None))


def test_resume_from_step_continues_numbering():
    calls: list[str] = []

    async def caller(name, **kwargs):
        calls.append(name)
        return "ok"

    steps = [{"tool": "ved_open"}, {"tool": "ved_apis"}, {"tool": "ved_tabs"}]
    record = asyncio.run(core.run(steps, caller=caller))
    resumed = asyncio.run(core.run(steps[2:], caller=caller, resume_of=record))
    assert calls == ["ved_open", "ved_apis", "ved_tabs", "ved_tabs"]
    assert [r.index for r in resumed.results] == [1, 2, 3, 4]
    assert resumed.done
