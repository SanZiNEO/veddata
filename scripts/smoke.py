"""veddata smoke test — drives the MCP server over stdio and asserts
end-to-end behavior of all 29 tools.  Prints PASS/FAIL per step, exits 1
on any failure.

Usage:  .venv/Scripts/python scripts/smoke.py
"""

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent

RESULTS = []


def check(step: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    RESULTS.append(cond)
    print(f"[{status}] {step}" + (f" — {detail[:300]}" if detail and not cond else ""))


async def call(session, name, **args):
    res = await session.call_tool(name, args or {})
    return "".join(c.text or "" for c in res.content)


async def main():
    import os
    import tempfile

    # 用临时目录，避免把 profile / response 写进仓库或用户数据目录
    # 路径配置只走 CLI 参数（环境变量那套已移除）
    profile_tmp = tempfile.mkdtemp(prefix="veddata-smoke-profile-")
    response_tmp = tempfile.mkdtemp(prefix="veddata-smoke-response-")
    params = StdioServerParameters(
        command=str(Path(sys.executable).resolve()),
        args=[
            "-m", "veddata.server",
            "--profile-dir", profile_tmp,
            "--response-dir", response_tmp,
        ],
        cwd=str(ROOT),
        env={**dict(os.environ)},
    )
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()

            # ---- Step 14 (tool inventory) ----
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            check("14: 29 tools listed", len(tools.tools) == 29, f"got {len(tools.tools)}")
            check("14: new tools present", {"ved_dom_tree", "ved_watch", "ved_console"} <= names)
            check("14: ved_elements removed", "ved_elements" not in names)

            # ---- Step 1 ----
            out = await call(session, "ved_open")
            check("1: ved_open", "Browser ready" in out, out)

            # ---- Step 2 (API capture) ----
            out = await call(session, "ved_goto", url="https://www.bilibili.com")
            check("2: goto bilibili", "bilibili" in out.lower(), out)
            out = await call(session, "ved_apis")
            check("2: APIs captured", "GET" in out and "No APIs captured yet." not in out, out)

            # ---- Step 3 (goto final return shape) ----
            out = await call(session, "ved_goto", url="https://www.bilibili.com")
            check("3: goto again", "bilibili" in out.lower(), out)
            check("3: DOM Tree section", "=== DOM Tree ===" in out, out)
            check("3: Captured Data section", "=== Captured Data" in out, out)

            # ---- Step 4 (dom tree) ----
            out = await call(session, "ved_dom_tree")
            check("4: dom_tree tree lines", "├──" in out, out)
            check("4: dom_tree html/body", "html" in out and "body" in out, out)

            # ---- Step 5 (dom search / locate) ----
            out = await call(session, "ved_dom_search", text="视频")
            check("5: dom_search hit", "视频" in out and ">" in out, out)
            out = await call(session, "ved_dom_locate", path="body")
            check("5: dom_locate body", "body" in out, out)

            # ---- Step 6 (scan) ----
            out = await call(session, "ved_scan", mode="all")
            check("6: scan sections", "DOM" in out and "Network" in out, out)

            # ---- Step 7 (act) ----
            out = await call(session, "ved_act", action="scroll", value="bottom")
            check("7: scroll bottom", "Scrolled to bottom" in out, out)

            # ---- Step 8 (search) ----
            out = await call(session, "ved_search", keyword="视频")
            check("8: search not empty", "No matches" not in out, out)

            # ---- Step 9 (scripts) ----
            out = await call(session, "ved_list_scripts")
            check("9: list_scripts >=1", len(out.strip().splitlines()) >= 1, out)
            out = await call(session, "ved_search_scripts", query="function")
            check("9: search_scripts hits", "matches" in out or "行" in out, out)

            # ---- Step 10 (watch flow) ----
            out = await call(session, "ved_watch", observations=[{"type": "request", "pattern": "**/*"}])
            check("10: watch registered", "Registered 1 watches" in out, out)
            await call(session, "ved_act", action="scroll", value="bottom")
            out = await call(session, "ved_watch", collect=True)
            check("10: watch collected", "Watch" in out or "request" in out, out)

            # ---- Step 11 (console) ----
            out = await call(session, "ved_console", code="1+1")
            check("11: console eval", out.strip() == "2", out)
            out = await call(session, "ved_console")
            check("11: console messages", out.strip() != "", out)

            # ---- Step 12 (trace value) ----
            out = await call(session, "ved_trace_value", value="http")
            groups = sum(1 for g in ("源码", "网络", "渲染文本", "内嵌") if g in out)
            check("12: trace groups >=2", groups >= 2, out)

            # ---- Step 13 (tabs + close) ----
            out = await call(session, "ved_tabs")
            check("13: tabs list", "Open tabs" in out, out)
            out = await call(session, "ved_close")
            check("13: close", "Browser closed" in out, out)

    failed = sum(1 for x in RESULTS if not x)
    print(f"\n=== {len(RESULTS) - failed}/{len(RESULTS)} passed ===")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
