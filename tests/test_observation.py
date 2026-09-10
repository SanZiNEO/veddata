"""observation.py：状态观测账本（先建档、再动手）的语义测试。"""

from __future__ import annotations

import pytest

from veddata import observation


@pytest.fixture(autouse=True)
def _fresh_ledger():
    observation.reset()
    yield
    observation.reset()


def test_unobserved_state_is_refused():
    with pytest.raises(observation.StatePolicyError) as excinfo:
        observation.require("ved_act")
    assert excinfo.value.code == observation.STATE_NOT_OBSERVED
    text = observation.remediate(excinfo.value)
    assert "ved_status()" in text and "ved_act" in text


def test_observe_unlocks_tools():
    observation.observe()
    observation.require("ved_act")                      # 不抛 = 放行


def test_change_after_observe_makes_it_stale_with_reason():
    observation.observe()
    observation.mark_dirty("页面跳转 → https://example.com/verify")
    with pytest.raises(observation.StatePolicyError) as excinfo:
        observation.require("ved_act")
    error = excinfo.value
    assert error.code == observation.STATE_STALE
    assert error.reasons == ["页面跳转 → https://example.com/verify"]
    assert "页面跳转" in observation.remediate(error)


def test_reobserve_clears_staleness():
    observation.observe()
    observation.mark_dirty("标签页被关闭（页面自己或用户）")
    assert observation.ledger().stale is True
    observation.observe()
    assert observation.ledger().stale is False
    assert observation.ledger().reasons == []
    observation.require("ved_watch")


def test_reasons_are_deduped_and_capped():
    for _ in range(3):
        observation.mark_dirty("新标签页被打开（页面自己或用户）")
    assert observation.ledger().reasons == ["新标签页被打开（页面自己或用户）"]
    assert observation.ledger().epoch == 3


def test_describe_mentions_both_epochs():
    observation.observe()
    observation.mark_dirty("页面跳转 → x")
    text = observation.ledger().describe()
    assert "epoch=1" in text and "observed=0" in text


def test_reset_forgets_everything():
    observation.observe()
    observation.mark_dirty("x")
    observation.reset()
    assert observation.ledger().observed_epoch is None
    with pytest.raises(observation.StatePolicyError):
        observation.require("ved_act")
