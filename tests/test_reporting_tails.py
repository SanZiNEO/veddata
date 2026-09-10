"""两个报告口径的小尾巴（实测后定的）：

1. 链步骤标签只留 URL 路径 —— 否则几条 goto 显示成一样的
2. 导航遇到"响应是文件"（Download is starting）要照实说"下载开始了"，不能报 failed
"""

from __future__ import annotations

import inspect

import veddata.server                                                              # noqa: F401
from veddata.tools import chain, navigate


def test_chain_label_shows_url_path_only():
    label = chain.label_of({"tool": "ved_goto",
                            "args": {"url": "https://www.svgrepo.com/svg/535197/arrow-u-up-left",
                                     "depth": 1}})
    assert "/svg/535197/arrow-u-up-left" in label
    assert "https://" not in label


def test_chain_label_keeps_other_values():
    label = chain.label_of({"tool": "ved_act", "args": {"action": "click", "target": "下一页"}})
    assert "click" in label and "下一页" in label


def test_chain_label_marks_repeat_round():
    label = chain.label_of({"tool": "ved_apis", "args": {}, "_round": 2})
    assert "第2轮" in label


def test_goto_reports_download_as_fact():
    source = inspect.getsource(navigate.ved_goto)
    assert "download started" in source
    assert "Download is starting" in source            # 只在这个条件下改口径
