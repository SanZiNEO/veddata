"""limits 模块测试 —— 锁死"别把上下文刷爆"的几条约定。

对齐的业界做法：opencode 的单行/字节上限、官方 fetch 的 start_index 续读、
DSH 的"截断+给下一步"。核心不是数值，而是**截断时必须说清楚怎么继续**。
"""

import pytest

from veddata import limits, paths


@pytest.fixture(autouse=True)
def clean_cli_config(monkeypatch):
    monkeypatch.setattr(paths, "_response_dir", None)


# ---- 单值 / 单行 ----------------------------------------------------------


def test_clip_keeps_short_values_and_truncates_long_ones():
    assert limits.clip("abc", 10) == "abc"
    clipped = limits.clip("a" * 100, 10)
    assert clipped.startswith("a" * 10)
    assert clipped.endswith(limits.ELLIPSIS)
    assert limits.clip(None) == ""


def test_clip_line_marks_where_it_cut():
    out = limits.clip_line("b" * 3000)
    assert out.startswith("b" * limits.MAX_LINE_CHARS)
    assert f"(line truncated to {limits.MAX_LINE_CHARS} chars)" in out
    assert limits.clip_line("short") == "short"


def test_describe_inline_never_leaks_the_payload():
    """页面里 200 KB+ 的 wasm/base64 只能给摘要 —— 这是最贵的那个坑。"""
    payload = "A" * 100_000
    out = limits.describe_inline(f"data:application/wasm;base64,{payload}")
    assert out == "data:(application/wasm, 100000 bytes)"
    assert "AAAA" not in out
    assert limits.describe_inline("https://x/y.js") == "https://x/y.js"


# ---- 分页 -----------------------------------------------------------------


def test_paginate_hands_out_the_next_offset():
    items = list(range(75))

    page, footer = limits.paginate(items, 0, 30)
    assert page == list(range(30))
    assert "offset=30" in footer

    page2, footer2 = limits.paginate(items, 30, 30)
    assert page2 == list(range(30, 60))
    assert "offset=60" in footer2

    page3, footer3 = limits.paginate(items, 60, 30)
    assert page3 == list(range(60, 75))
    assert "已全部显示" in footer3, "最后一页不该再让人继续翻"


def test_paginate_handles_empty_and_out_of_range():
    page, footer = limits.paginate([], 0, 10)
    assert page == [] and "共 0" in footer

    page2, footer2 = limits.paginate([1, 2, 3], offset=99, limit=10)
    assert page2 == [] and "共 3" in footer2


# ---- 整块截断 + spill ------------------------------------------------------


def test_short_text_passes_through():
    assert limits.truncate_text("hello") == "hello"


def test_long_text_truncates_without_spill_when_unconfigured():
    out = limits.truncate_text("x" * 100, limit=10)
    assert out.startswith("x" * 10)
    assert "输出超过上限" in out
    assert "全量已写入" not in out, "没配 --response-dir 就不能假装写了文件"


def test_long_text_spills_when_response_dir_configured(tmp_path):
    paths.set_response_dir(tmp_path)
    text = "y" * 50
    out = limits.truncate_text(text, limit=10, hint="demo")

    assert "全量已写入" in out
    spilled = list((tmp_path / limits.SPILL_DIRNAME).glob("*.txt"))
    assert len(spilled) == 1
    assert spilled[0].read_text(encoding="utf-8") == text


def test_spill_directory_is_pruned(tmp_path, monkeypatch):
    monkeypatch.setattr(limits, "SPILL_KEEP", 2)
    paths.set_response_dir(tmp_path)
    for i in range(5):
        limits.spill(f"body-{i}", hint=f"demo{i}")
    kept = list((tmp_path / limits.SPILL_DIRNAME).glob("*.txt"))
    assert len(kept) == 2, "spill 目录不能无限涨"


# ---- 参数收口 --------------------------------------------------------------


def test_clamp_falls_back_on_garbage():
    assert limits.clamp(0, low=1, high=8, default=2) == 2
    assert limits.clamp(-5, low=1, high=8, default=2) == 2
    assert limits.clamp("x", low=1, high=8, default=2) == 2
    assert limits.clamp(None, low=1, high=8, default=2) == 2
    assert limits.clamp(99, low=1, high=8, default=2) == 8
    assert limits.clamp(4, low=1, high=8, default=2) == 4
