"""工具链端到端验收：一条 ved_chain 替代多轮往返，并把因果（差分）说清楚。

复用 test_attach_parity.py 里的本地 fixture 站点（不外网、可复现）。

验收点：
1. `open → goto → watch(注册) → act(click) → wait → watch(collect)` 一条链跑完（原本 6+ 次往返）
2. 报告里每个动作步骤都带**因果差分**（"+1 requests: items.json"）
3. `repeat` 块能翻页式重复动作，且每轮差分单独归因
4. 链结束后的细节仍在服务端（ved_apis / ved_inspect 可取）
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import test_attach_parity as parity                                                   # noqa: E402
from http.server import ThreadingHTTPServer                                            # noqa: E402


async def main() -> int:
    from fastmcp import FastMCP

    from veddata import paths, state

    state.mcp = FastMCP("veddata-chain-e2e")
    import veddata.tools.act                                                           # noqa: F401
    import veddata.tools.chain_tool                                                    # noqa: F401
    import veddata.tools.discover                                                      # noqa: F401
    import veddata.tools.navigate                                                      # noqa: F401
    import veddata.tools.observe                                                       # noqa: F401
    import veddata.tools.scan                                                         # noqa: F401
    from veddata.tools.chain_tool import ved_chain
    from veddata.tools.discover import ved_inspect

    server = ThreadingHTTPServer(("127.0.0.1", 0), parity.FixtureHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/index.html"
    out_dir = Path(tempfile.mkdtemp(prefix="veddata-chain-out-"))
    import os
    os.environ["HEADLESS"] = "true"
    paths.set_profile_dir(Path(tempfile.mkdtemp(prefix="veddata-chain-profile-")))
    paths.set_response_dir(out_dir)

    pattern = "*items.json*"
    steps_one = [
        {"tool": "ved_open"},
        {"tool": "ved_goto", "args": {"url": base, "depth": 1, "limit": 3}},
        {"tool": "ved_watch", "args": {"observations": [{"type": "request", "pattern": pattern}]}},
        {"tool": "ved_act", "args": {"action": "click", "target": "LoadMore"}},
        {"wait": {"network_idle": 600, "timeout": 8}},
        {"tool": "ved_watch", "args": {"collect": True, "timeout": 8}},
    ]
    print("=== 链 1：open→goto→watch→act→wait→collect（1 次往返，6 步）===")
    report_one = await ved_chain(steps=steps_one, step_delay_ms=150)
    print(report_one)

    steps_two = [
        {"repeat": {"times": 2, "steps": [
            {"tool": "ved_act", "args": {"action": "click", "target": "LoadMore"}},
            {"wait": {"network_idle": 500, "timeout": 6}},
        ]}},
        {"tool": "ved_apis"},
    ]
    print("\n=== 链 2：repeat 翻页两次 + 取接口清单（1 次往返，4 步展开）===")
    report_two = await ved_chain(steps=steps_two, step_delay_ms=150)
    print(report_two)

    print("\n=== 链结束后细节仍在服务端（ved_apis / ved_inspect 可取）===")
    for index in range(1, 6):
        text = ved_inspect(index=index)
        if "items" in text and "not found" not in text:
            print(f"  ved_inspect(index={index}) → {text.splitlines()[2][:110]}")
            break
    server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
