"""Web Scout MCP Server v1.0 — Entry point with 29 tools."""

import os

from fastmcp import FastMCP

from web_scout import state
from web_scout.browser import BrowserSession
from web_scout.network_monitor import NetworkMonitor

_response_dir = os.environ.get("RESPONSE_DIR", "./response")
state._response_dir = _response_dir
if os.path.exists(_response_dir):
    import shutil
    shutil.rmtree(_response_dir)

mcp = FastMCP("web-scout", instructions="""
Web Scout 是数据源发现工具，不是浏览器。用于分析页面数据来源、捕获 API、
跟踪数据流。如果你只是要看一个网页，有其他 MCP 工具更合适。

TAB IDs: 所有 tab 用短 ID（前 8 字符，前缀匹配）。
  scout_tab_switch("5FD84E84") — 切换 tab

RECOMMENDED WORKFLOW:
  scout_open() -> scout_goto(url)      # 返回 DOM 树 + 数据源清单
  scout_dom_search(keyword)            # 在内存 DOM 树中定位关键词
  scout_search(keyword)                # 跨网络/内嵌/脚本/全局变量搜索
  scout_trace_value(value)             # 追踪一个值流经的所有位置
  scout_watch(observations=[...])      # 注册观测点
  scout_act("click", target="加载更多") # 触发 → scout_watch(collect=True) 收快照
  scout_console(code="...")            # 页面内执行 JS 验证

页面访问（scout_goto/scout_fetch）是发现数据的前置步骤，不是功能主体。
""")

state.mcp = mcp

import web_scout.tools.navigate
import web_scout.tools.observe
import web_scout.tools.act
import web_scout.tools.discover
import web_scout.tools.scan


def main():
    mcp.run()


if __name__ == "__main__":
    main()
