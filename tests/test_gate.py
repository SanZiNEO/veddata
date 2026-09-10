"""gate.py：人机门判定的纯逻辑测试（不需要浏览器）。"""

from __future__ import annotations

import pytest

from veddata import gate


@pytest.fixture(autouse=True)
def _clean_baselines():
    gate.reset()
    yield
    gate.reset()


def info(url="https://example.com/list", title="列表", text="正常内容" * 100,
         length=None, password=False, widgets=0) -> dict:
    return {"url": url, "title": title, "text": text, "len": length if length is not None else len(text),
            "password": password, "widgets": widgets}


def test_verify_url_is_a_hard_risk_gate():
    result = gate._judge(info(url="https://www.zhipin.com/web/passport/zp/verify.html"), "t1")
    assert result is not None and result.kind == gate.RISK_CONTROL
    assert result.hard is True
    assert "verify.html" in result.evidence[0]


def test_known_widget_means_captcha():
    result = gate._judge(info(widgets=2), "t1")
    assert result is not None and result.kind == gate.CAPTCHA and result.hard


def test_marker_text_means_captcha():
    result = gate._judge(info(text="请完成验证后继续访问"), "t1")
    assert result is not None and result.kind == gate.CAPTCHA and result.hard


def test_english_cloudflare_marker_means_risk_control():
    result = gate._judge(info(text="Checking your browser before accessing the site."), "t1")
    assert result is not None and result.kind == gate.RISK_CONTROL and result.hard


def test_password_field_is_a_login_gate():
    result = gate._judge(info(password=True), "t1")
    assert result is not None and result.kind == gate.LOGIN and result.hard


def test_normal_page_is_not_a_gate_and_sets_baseline():
    assert gate._judge(info(), "t1") is None
    assert gate._baselines["t1"][1] > 0


def test_dom_collapse_is_only_a_soft_hint():
    gate._judge(info(url="https://a.com/x", length=2903), "t1")          # 基线
    result = gate._judge(info(url="https://a.com/x", text="短", length=101), "t1")
    assert result is not None and result.kind == gate.RISK_CONTROL
    assert result.hard is False                                          # 弱信号不硬停
    assert "缩到" in result.evidence[0]


def test_gate_page_does_not_poison_the_baseline():
    gate._judge(info(url="https://a.com/x", length=2903), "t1")
    gate._judge(info(url="https://a.com/x", text="", length=0), "t1")     # 被擦
    assert gate._baselines["t1"][1] == 2903


def test_format_gate_tells_ai_what_to_do():
    result = gate._judge(info(widgets=1), "t1")
    text = gate.format_gate(result, "[ABC12345] https://a.com")
    assert "需要人工" in text
    assert "不要重新导航" in text
    assert "ved_status()" in text
    assert "ved_apis" in text


def test_format_gate_marks_low_confidence():
    gate._judge(info(url="https://a.com/x", length=2903), "t1")
    result = gate._judge(info(url="https://a.com/x", length=50), "t1")
    assert "低置信" in gate.format_gate(result)


def test_reset_clears_one_tab_or_all():
    gate._judge(info(url="https://a.com/x"), "t1")
    gate._judge(info(url="https://a.com/y"), "t2")
    gate.reset("t1")
    assert "t1" not in gate._baselines and "t2" in gate._baselines
    gate.reset()
    assert gate._baselines == {}


class _FakePage:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.seen_js = ""

    async def evaluate(self, js):
        self.seen_js = js
        return self.payload


def test_detect_async_reads_the_page_and_reports():
    import asyncio

    page = _FakePage(info(url="https://a.com/web/passport/zp/verify.html"))
    result = asyncio.run(gate.detect_async(page, "t1"))
    assert result is not None and result.kind == gate.RISK_CONTROL
    assert "password" in page.seen_js                                     # 确实查了密码框


def test_detect_async_survives_broken_page():
    import asyncio

    class _Broken:
        async def evaluate(self, js):
            raise RuntimeError("target closed")

    assert asyncio.run(gate.detect_async(_Broken(), "t1")) is None
