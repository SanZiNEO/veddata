"""gate.py：页面事实采集的纯逻辑测试（不需要浏览器）。

原则：**只说有什么，不判定、不引导**。所以测试里断言的是"事实被正确采集/呈现"，
以及"输出里不含任何建议动作"。
"""

from __future__ import annotations

import asyncio

import pytest

from veddata import gate


@pytest.fixture(autouse=True)
def _clean_baselines():
    gate.reset()
    yield
    gate.reset()


def info(url="https://example.com/list", title="列表", text="正常内容" * 100,
         links=12, visible=None, hidden=None) -> dict:
    return {"url": url, "title": title, "length": len(text), "links": links, "sample": text,
            "widgetsVisible": visible or [], "widgetsHidden": hidden or []}


def test_no_verdict_fields_exist():
    """我们不再判定性质：模块里不该有 kind / confidence 这类东西。"""
    facts = gate._facts(info(), "t1")
    assert not hasattr(facts, "kind")
    assert not hasattr(facts, "confidence")
    assert facts.hard is False                 # 永久 False：不替 AI 决定停不停


def test_keyword_hit_carries_original_context():
    text = "前面一堆无关内容" * 5 + "请完成验证后继续访问" + "后面一堆无关内容" * 5
    facts = gate._facts(info(text=text), "t1")
    words = [word for word, _ in facts.hits]
    assert "验证" in words
    context = dict(facts.hits)["验证"]
    assert "请完成验证后继续访问" in context        # 原文片段，不是加工过的结论


def test_no_hit_reports_none():
    facts = gate._facts(info(text="普通页面，没什么特别的"), "t1")
    assert facts.hits == []
    assert "hit     : (none)" in gate.format_facts(facts)


def test_size_change_is_a_number_not_a_judgement():
    gate._facts(info(url="https://a.com/x", text="x" * 2903), "t1")
    facts = gate._facts(info(url="https://a.com/x", text="x" * 101), "t1")
    assert facts.size_change == "2903 → 101 chars (same address)"


def test_visible_and_hidden_widgets_are_reported_separately():
    facts = gate._facts(info(visible=[["#nc_1_wrapper", "300x40"]], hidden=["input[type=password]"]), "t1")
    text = gate.format_facts(facts)
    assert "visible : #nc_1_wrapper 300x40" in text
    assert "hidden  : input[type=password]" in text


def test_output_contains_no_advice():
    """没有任何"该做什么"的话术（这是仓库既定原则）。"""
    facts = gate._facts(info(text="请完成验证后继续访问"), "t1")
    text = gate.format_facts(facts)
    for forbidden in ("需要人工", "不要重新导航", "先调", "续跑", "请用户", "下一步"):
        assert forbidden not in text


def test_format_lists_url_title_body():
    facts = gate._facts(info(url="https://a.com/verify.html", title="安全验证", text="abc" * 40), "t1")
    text = gate.format_facts(facts)
    assert "https://a.com/verify.html" in text
    assert "安全验证" in text
    assert "120 chars, 12 links" in text


def test_reset_clears_one_tab_or_all():
    gate._facts(info(url="https://a.com/x"), "t1")
    gate._facts(info(url="https://a.com/y"), "t2")
    gate.reset("t1")
    assert "t1" not in gate._baselines and "t2" in gate._baselines
    gate.reset()
    assert gate._baselines == {}


class _FakePage:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.seen_js = ""

    async def evaluate(self, js):
        self.seen_js = js
        return self.payload


def test_collect_reads_the_page_once():
    page = _FakePage(info(text="请完成验证"))
    facts = asyncio.run(gate.collect(page, "t1"))
    assert facts is not None and facts.length > 0
    assert "widgetsVisible" in page.seen_js                    # 确实去查了组件事实


def test_collect_survives_broken_page():
    class _Broken:
        async def evaluate(self, js):
            raise RuntimeError("target closed")

    assert asyncio.run(gate.collect(_Broken(), "t1")) is None


def test_legacy_aliases_still_work_for_call_sites():
    """调用点仍用 detect_async/format_gate/hard，语义已是"只给事实"。"""
    page = _FakePage(info(text="正常"))
    facts = asyncio.run(gate.detect_async(page, "t1"))
    assert facts.hard is False
    assert "page facts" in gate.format_gate(facts)
