"""工具层接线冒烟测试：导入不炸、门禁真的生效、等待类工具确已移除。"""

from __future__ import annotations

import asyncio

from veddata import observation


def test_server_imports_all_tool_modules():
    import veddata.server                                                            # noqa: F401


def test_new_and_removed_tools():
    import veddata.tools.act as act
    import veddata.tools.navigate as navigate

    assert hasattr(navigate, "ved_status")
    assert not hasattr(act, "ved_login")            # 等待类工具已移除
    assert not hasattr(navigate, "ved_login")


def test_gated_tool_refuses_until_state_observed():
    import veddata.server                                                            # noqa: F401
    from veddata import state
    from veddata.tools.act import ved_act

    state._browser = None
    observation.reset()
    refused = asyncio.run(ved_act(action="scroll", value="bottom"))
    assert "ved_status()" in refused and "browser state" in refused

    observation.observe()
    allowed = asyncio.run(ved_act(action="scroll", value="bottom"))
    assert "ved_status()" not in allowed                 # 放行后走到原来的实现（无浏览器会话）


def test_gated_tool_reports_what_changed():
    import veddata.server                                                            # noqa: F401
    from veddata import state
    from veddata.tools.observe import ved_dom_tree

    state._browser = None
    observation.observe()
    observation.mark_dirty("页面跳转 → https://x/verify")
    refused = asyncio.run(ved_dom_tree())
    assert "页面跳转" in refused and "ved_status()" in refused
