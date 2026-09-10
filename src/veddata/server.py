"""veddata（斥候）MCP Server v1.0 — Entry point with 29 tools."""

import argparse
import sys

from fastmcp import FastMCP

from veddata import paths, state
from veddata.browser import BrowserSession
from veddata.network_monitor import NetworkMonitor

mcp = FastMCP("veddata", instructions="""
veddata（斥候）是数据源发现工具，不是浏览器。用于分析页面数据来源、捕获 API、
跟踪数据流。如果你只是要看一个网页，有其他 MCP 工具更合适。

TAB IDs: 所有 tab 用短 ID（前 8 字符，前缀匹配）。
  ved_tab_switch("5FD84E84") — 切换 tab

RECOMMENDED WORKFLOW:
  ved_open() -> ved_goto(url)         # 返回 DOM 树 + 数据源清单
  ved_dom_search(keyword)             # 在内存 DOM 树中定位关键词
  ved_search(keyword)                 # 跨网络/内嵌/脚本/全局变量搜索
  ved_trace_value(value)              # 追踪一个值流经的所有位置
  ved_watch(observations=[...])       # 注册观测点
  ved_act("click", target="加载更多")  # 触发 → ved_watch(collect=True) 收快照
  ved_console(code="...")             # 页面内执行 JS 验证

页面访问（ved_goto/ved_fetch）是发现数据的前置步骤，不是功能主体。

写文件的工具（ved_export / ved_export_all / ved_screenshot）需要目标目录：
启动时用 --response-dir 指定，或本次调用传 output_dir（绝对路径）。
""")

state.mcp = mcp

import veddata.tools.navigate
import veddata.tools.observe
import veddata.tools.act
import veddata.tools.discover
import veddata.tools.scan


def _parse_args(argv=None):
    """路径配置只有命令行参数这一条通路（args 是各客户端都有的公共面）。"""
    parser = argparse.ArgumentParser(prog="veddata", description="veddata（斥候）MCP server")
    parser.add_argument(
        "--profile-dir",
        metavar="DIR",
        help="浏览器 profile 目录（绝对路径），保留登录态；"
             "默认 <用户数据根>/veddata/profile",
    )
    parser.add_argument(
        "--response-dir",
        metavar="DIR",
        help="导出 / 截图落地目录（绝对路径）；不配置则写盘时报错",
    )
    return parser.parse_args(argv)


def main():
    args = _parse_args()

    if args.profile_dir:
        paths.set_profile_dir(args.profile_dir)
    if args.response_dir:
        paths.set_response_dir(args.response_dir)

    # 启动只做一次预检并把结果写到 stderr，**不因为路径有问题就让整个服务起不来**：
    # 不写盘的那些工具不该被一条导出路径拖下水。真正的失败发生在要写盘的那一刻。
    for label, raw in (("--profile-dir", args.profile_dir), ("--response-dir", args.response_dir)):
        if not raw:
            continue
        try:
            paths.prepare_dir(raw, what=label)
        except paths.PathError as exc:
            print(f"[veddata] {exc}", file=sys.stderr)

    print(f"[veddata] {paths.describe()}", file=sys.stderr)

    mcp.run()


if __name__ == "__main__":
    main()
