"""先读后打策略测试 —— 对齐 deepseek-harness 的 ``fs-observation-policy``。

锁死四条：
1. 没读过 → ``WATCH_NOT_READ``，文案必须给出去调 ``ved_script_source`` 的恢复动作；
2. 读过后内容变了 → ``WATCH_STALE``，文案要求重读；
3. 脚本不在注册表 → ``WATCH_NOT_FOUND``，文案指向 ``ved_list_scripts``；
4. 账本按 tab 隔离，且可以忘掉某个 tab。
"""

import pytest

from veddata import watch_policy
from veddata.watch_policy import ObservationLedger, WatchPolicyError, fingerprint


@pytest.fixture(autouse=True)
def clean_ledger():
    watch_policy.ledger().clear()
    yield
    watch_policy.ledger().clear()


# ---- 指纹 ------------------------------------------------------------------


def test_fingerprint_tracks_lines_and_content():
    base = fingerprint("a\nb\nc")
    assert base.startswith("3:"), "前缀是行数，便于一眼看出规模"
    assert fingerprint("a\nb\nc") == base, "同一内容指纹稳定"
    assert fingerprint("a\nb\nd") != base, "内容变了指纹必须变"
    assert fingerprint("a\nb") != base, "行数变了指纹必须变"


def test_ledger_records_and_forgets():
    led = ObservationLedger()
    led.observe("t1", "https://x/app.js", "hello")
    assert led.observed("t1", "https://x/app.js") == fingerprint("hello")
    assert led.observed("t2", "https://x/app.js") is None, "按 tab 隔离"

    led.forget_tab("t1")
    assert led.observed("t1", "https://x/app.js") is None


# ---- 三个决策 -------------------------------------------------------------


def test_missing_observation_is_refused_with_read_remedy():
    with pytest.raises(WatchPolicyError) as exc:
        watch_policy.check_read("t1", "https://x/app.js", "line1")
    assert exc.value.code == watch_policy.WATCH_NOT_READ

    message = watch_policy.remediate(exc.value, "https://x/app.js", 42)
    assert "has not been read" in message
    assert "ved_script_source" in message, "必须给出恢复动作"
    assert "42" in message, "带上行号，便于直接照抄重试"


def test_observing_once_allows_the_watch():
    watch_policy.ledger().observe("t1", "https://x/app.js", "line1\nline2")
    watch_policy.check_read("t1", "https://x/app.js", "line1\nline2")   # 不抛即通过


def test_changed_source_requires_a_reread():
    watch_policy.ledger().observe("t1", "https://x/app.js", "line1\nline2")
    with pytest.raises(WatchPolicyError) as exc:
        watch_policy.check_read("t1", "https://x/app.js", "line1\nCHANGED")
    assert exc.value.code == watch_policy.WATCH_STALE

    message = watch_policy.remediate(exc.value, "https://x/app.js", 3)
    assert "changed since it was read" in message
    assert "re-read" in message


def test_unknown_script_points_at_list_scripts():
    with pytest.raises(WatchPolicyError) as exc:
        watch_policy.check_read("t1", "https://x/missing.js", None)
    assert exc.value.code == watch_policy.WATCH_NOT_FOUND

    message = watch_policy.remediate(exc.value, "https://x/missing.js", 1)
    assert "ved_list_scripts" in message


def test_ledger_is_per_tab_end_to_end():
    watch_policy.ledger().observe("t1", "https://x/app.js", "a")

    watch_policy.check_read("t1", "https://x/app.js", "a")            # 本 tab 通过
    with pytest.raises(WatchPolicyError) as exc:
        watch_policy.check_read("t2", "https://x/app.js", "a")        # 别的 tab 没读过
    assert exc.value.code == watch_policy.WATCH_NOT_READ
