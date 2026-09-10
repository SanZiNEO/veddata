"""act.py：target 的选择器支持（不需要浏览器）。

背景：只能按可见文本定位时，"点那个下载链接"点不准 —— svgrepo 那次点到了外层
（报 Clicked 但 Downloads 里没文件）。所以 target 支持 css= / xpath= / // 前缀。
"""

from __future__ import annotations

import asyncio

import veddata.server                                                              # noqa: F401  注册工具（设置 state.mcp）
from veddata.tools import act as act_mod


def test_is_selector():
    assert act_mod._is_selector("css=a[href*='/download/']")
    assert act_mod._is_selector("xpath=//a[@id='x']")
    assert act_mod._is_selector("//a[contains(@href,'/download/')]")
    assert not act_mod._is_selector("Download SVG Vector")
    assert not act_mod._is_selector("下一页")


class FakeLocator:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.clicked = 0

    @property
    def first(self):
        return self

    async def click(self, timeout=None):
        self.clicked += 1
        if not self.ok:
            raise RuntimeError("no match")

    async def fill(self, value):
        pass

    def filter(self, **kwargs):
        return self


class FakePage:
    def __init__(self, ok: bool = True) -> None:
        self.locator_used: list[str] = []
        self._locator = FakeLocator(ok)

    def locator(self, selector):
        self.locator_used.append(selector)
        return self._locator

    def get_by_placeholder(self, text):
        raise AssertionError("选择器命中时不该走文本匹配")


def test_selector_target_uses_locator():
    page = FakePage()
    found = asyncio.run(act_mod._find_locator(page, "css=a[href*='/download/']", "a,button,span"))
    assert found is not None
    assert page.locator_used == ["css=a[href*='/download/']"]


def test_xpath_target_uses_locator():
    page = FakePage()
    asyncio.run(act_mod._find_locator(page, "//a[contains(@href,'/download/')]", "a,button,span"))
    assert page.locator_used == ["//a[contains(@href,'/download/')]"]


def test_selector_no_match_returns_none():
    page = FakePage(ok=False)
    assert asyncio.run(act_mod._find_locator(page, "css=a[href*='/nope/']", "a,button,span")) is None


def test_plain_text_still_uses_text_matching():
    """不带前缀的目标仍然走文本匹配（保持原行为）。"""
    class TextPage(FakePage):
        def get_by_role(self, role, name=None):
            return FakeLocator(ok=True)

        def get_by_text(self, text, exact=False):
            return FakeLocator(ok=True)

    page = TextPage()
    found = asyncio.run(act_mod._find_locator(page, "下一页", "a,button,span"))
    assert found is not None
    assert all(not s.startswith(("css=", "//", "xpath=")) for s in page.locator_used)   # 没走选择器分支
