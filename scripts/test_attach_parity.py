"""对照测试：attach 模式（自起 Chrome + connect_over_cdp）会不会让 veddata 的工具功能打折扣。

两种模式
--------
- ``--mode launch``：产品现在的默认 —— ``launch_persistent_context``（Playwright 起浏览器）
- ``--mode attach``：DrissionPage 式 —— 自己 Popen 一个普通 Chrome（``--remote-debugging-port``）
  + ``connect_over_cdp``（``BROWSER_ADDRESS`` 分支，代码里现成）

测什么
------
本地 fixture 站点（不依赖外网），把我们真实用到的能力逐项对照：

  导航/标签、控制台历史、控制台执行 JS、执行后再看历史、API 捕获、API 详情+请求重放、
  脚本清单、脚本源码、脚本搜索、**请求观测点（page.route）**、**JS 观测点（Debugger 断点）**、
  DOM 树、全页扫描、DOM 搜索、动作（输入/点击）、cookie、截图写盘、
  页面自开新标签自动注册、**close() 语义（会不会连别人的浏览器/标签一起关）**

判定要点（避免假 PASS）
-----------------------
- 请求观测点：认 **``page=2``** —— 只有点击触发的那个请求才有；注册输出里不会有
- JS 观测点：认 **``TICK_``** —— 断点真的命中才会读到变量值；注册输出里只有变量名 ``tickValue``
- 控制台：先看脚本自带日志（``VED_MARKER_HELLO``），再看"我们自己执行 JS 之后产生的日志"

用法::

    .venv\\Scripts\\python.exe scripts\\test_attach_parity.py --mode launch
    .venv\\Scripts\\python.exe scripts\\test_attach_parity.py --mode attach
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

APP_JS = """console.log("VED_MARKER_HELLO");
window.fixtureFetch = function (page) {
  return fetch("/api/items.json?page=" + page).then(function (r) { return r.json(); });
};
function fixtureTick() {
  var tickValue = "TICK_" + Math.random();
  return tickValue;
}
window.fixtureTick = fixtureTick;
window.fixtureFetch(1).then(function (d) { console.log("VED_MARKER_FETCH1", d.items.length); });
setTimeout(function () { console.warn("VED_MARKER_LATE"); }, 400);
"""

INDEX_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>VEDFixture</title>
<script src="/app.js"></script></head>
<body><h1>VEDFIXTURE_BODY</h1>
<input id="kw" placeholder="kw">
<button id="loadmore" onclick="window.fixtureFetch(2).then(function(d){document.getElementById('hits').textContent='HITS_'+d.items.length;});">LoadMore</button>
<button id="popup" onclick="window.open('/second.html','_blank');">Popup</button>
<div id="hits">HITS_0</div>
<div class="card" data-x="1">CARD_ONE</div>
</body></html>"""

SECOND_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>VEDSecond</title></head>
<body>VEDSECOND_BODY</body></html>"""


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):                                              # noqa: A003
        pass

    def _send(self, body: bytes, headers: dict, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                                                          # noqa: N802
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            self._send(INDEX_HTML.encode("utf-8"),
                       {"Content-Type": "text/html; charset=utf-8", "Set-Cookie": "vedparity=1; Path=/"})
        elif path == "/app.js":
            self._send(APP_JS.encode("utf-8"),
                       {"Content-Type": "application/javascript; charset=utf-8"})
        elif path == "/api/items.json":
            payload = {"items": [{"id": i, "name": f"ITEM_{i}"} for i in range(1, 6)], "page": 1}
            self._send(json.dumps(payload).encode("utf-8"),
                       {"Content-Type": "application/json; charset=utf-8"})
        elif path == "/second.html":
            self._send(SECOND_HTML.encode("utf-8"), {"Content-Type": "text/html; charset=utf-8"})
        else:
            self._send(b"not found", {"Content-Type": "text/plain"}, status=404)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def cdp_target_count(port: int) -> int:
    """借 CDP 的 /json/list 数 target（不经过 Playwright）—— 只对 attach 模式有意义。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as response:
            return len(json.loads(response.read().decode("utf-8", "replace")))
    except Exception:                                                          # noqa: BLE001
        return -1


def unwrap(func):
    return getattr(func, "fn", getattr(func, "__wrapped__", func))


async def call(func, *args, **kwargs):
    """统一调用：FastMCP 装饰器解包 + 同步/异步都能用。"""
    target = unwrap(func)
    result = target(*args, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result


class Battery:
    def __init__(self) -> None:
        self.results: list[dict] = []

    def _add(self, entry: dict) -> None:
        self.results.append(entry)
        flag = "PASS" if entry["ok"] else "FAIL"
        print(f"    {flag} {entry['name']:<19} {entry['ms']:>5}ms  {str(entry['detail'])[:120]}", flush=True)

    async def step(self, name: str, factory, check) -> str:
        started = time.time()
        try:
            value = await factory()
            ok, detail = check(value)
            entry = {"name": name, "ok": bool(ok), "detail": str(detail),
                     "output": value if isinstance(value, str) else str(value)}
        except Exception as exc:                                               # noqa: BLE001
            entry = {"name": name, "ok": False, "detail": f"EXC {type(exc).__name__}: {str(exc)[:200]}",
                     "output": ""}
        entry["ms"] = int((time.time() - started) * 1000)
        self._add(entry)
        return entry["output"]

    def info(self, name: str, detail: str, output: str = "") -> None:
        self._add({"name": name, "ok": True, "detail": f"INFO {detail}", "output": output, "ms": 0})


def has(needle: str):
    def check(value) -> tuple[bool, str]:
        text = str(value)
        return needle in text, f"{'has' if needle in text else 'MISSING'} {needle!r} len={len(text)}"
    return check


async def run_battery(base_url: str, app_js_url: str, tick_line: int,
                      output_dir: Path, cdp_port: int) -> Battery:
    from fastmcp import FastMCP

    from veddata import state

    state.mcp = FastMCP("veddata-parity")
    import veddata.tools.act                                                        # noqa: F401
    import veddata.tools.discover                                                   # noqa: F401
    import veddata.tools.navigate                                                   # noqa: F401
    import veddata.tools.observe                                                    # noqa: F401
    import veddata.tools.scan                                                       # noqa: F401
    from veddata.tools.act import ved_act
    from veddata.tools.discover import (ved_apis, ved_inspect, ved_list_scripts,
                                        ved_request, ved_script_source,
                                        ved_search_scripts, ved_watch)
    from veddata.tools.navigate import ved_close, ved_goto, ved_open, ved_tabs
    from veddata.tools.observe import (ved_console, ved_cookies, ved_dom_search,
                                       ved_dom_tree, ved_screenshot)
    from veddata.tools.scan import ved_scan

    battery = Battery()

    await battery.step("open", lambda: call(ved_open),
                       lambda v: ("Error" not in str(v), str(v)[:70]))
    await battery.step("goto", lambda: call(ved_goto, base_url), has("VEDFixture"))
    await asyncio.sleep(1.2)
    await battery.step("console_history", lambda: call(ved_console), has("VED_MARKER_HELLO"))
    await battery.step("console_eval", lambda: call(ved_console, code="document.title"), has("VEDFixture"))
    await battery.step("console_after_eval",
                       lambda: call(ved_console, code='(console.log("VED_MARKER_EVAL"), document.title)'),
                       has("VEDFixture"))
    await battery.step("console_history2", lambda: call(ved_console), has("VED_MARKER_EVAL"))

    apis_text = await battery.step("apis", lambda: call(ved_apis), has("items.json"))
    await battery.step("dom_tree", lambda: call(ved_dom_tree, depth=2), has("body"))
    await battery.step("scan", lambda: call(ved_scan),
                       lambda v: (len(str(v)) > 50, f"len={len(str(v))}"))
    await battery.step("dom_search", lambda: call(ved_dom_search, "VEDFIXTURE_BODY"), has("VEDFIXTURE"))
    await battery.step("cookies", lambda: call(ved_cookies), has("vedparity"))
    await battery.step("list_scripts", lambda: call(ved_list_scripts), has("app.js"))
    await battery.step("script_source", lambda: call(ved_script_source, url=app_js_url), has("fixtureTick"))
    await battery.step("search_scripts", lambda: call(ved_search_scripts, query="fixtureTick"), has("app.js"))

    async def inspect_and_replay() -> str:
        for index in range(1, 8):
            text = await call(ved_inspect, index=index)
            if "items" in text and "not found" not in text:
                replayed = await call(ved_request, index=index)
                return f"[inspect#{index}]\n{text[:400]}\n[replay]\n{replayed[:400]}"
        return "no items API found"

    await battery.step("inspect_replay", inspect_and_replay,
                       lambda v: ("[inspect#" in str(v) and "200" in str(v), str(v)[:70]))

    async def input_then_read() -> str:
        first = await call(ved_act, action="input", value="hello", target="kw")
        value = await call(ved_console, code="document.querySelector('#kw').value")
        return f"{first} | value={value}"

    await battery.step("act_input", input_then_read, has("hello"))

    async def shot() -> str:
        return await call(ved_screenshot, name="parity", output_dir=str(output_dir))

    def shot_check(_value) -> tuple[bool, str]:
        files = sorted(output_dir.glob("*.png"))
        size = files[-1].stat().st_size if files else 0
        return bool(files) and size > 1000, f"files={len(files)} last={size}B"

    await battery.step("screenshot", shot, shot_check)

    # ---- 请求观测点（page.route）：判定认 page=2（只有点击触发的请求才有）----
    async def request_watch() -> str:
        before = await call(ved_apis)
        registered = await call(ved_watch,
                                observations=[{"type": "request", "pattern": "**/items.json*"}])
        battery.info("watch_request.reg", registered[:90].replace("\n", " "), registered)
        clicked = await call(ved_act, action="click", target="LoadMore")
        await asyncio.sleep(1.5)
        hits = await call(ved_console, code="document.getElementById('hits').textContent")
        after = await call(ved_apis)
        report = await call(ved_watch, collect=True, timeout=8)
        battery.info("watch_request.trigger",
                     f"click={str(clicked).strip()[:40]} hits_text={hits} "
                     f"apis {str(before).count('items.json')}→{str(after).count('items.json')}",
                     f"{clicked}\n{hits}\n{after}")
        battery.info("watch_request.rep", report[:90].replace("\n", " "), report)

        if "page=2" not in report:
            # 退化路径：换成正则再试一次，确认是"模式问题"还是"写法问题"
            await call(ved_watch, remove="all")
            registered2 = await call(ved_watch,
                                     observations=[{"type": "request", "pattern": "/items\\.json/"}])
            battery.info("watch_request.reg2", registered2[:90].replace("\n", " "), registered2)
            await call(ved_console, code="fixtureFetch(2)")
            await asyncio.sleep(1.5)
            report2 = await call(ved_watch, collect=True, timeout=8)
            battery.info("watch_request.rep2", report2[:90].replace("\n", " "), report2)
            return report + "\n=== retry with /regex/ ===\n" + report2
        return report

    await battery.step("watch_request", request_watch, has("page=2"))

    # ---- JS 观测点（Debugger 断点）：判定认 TICK_（真命中才读得到值）----
    async def js_watch() -> str:
        registered = await call(ved_watch, observations=[{
            "type": "js", "url": app_js_url, "line": tick_line, "variables": ["tickValue"],
        }])
        battery.info("watch_js.reg", registered[:80].replace("\n", " "), registered)
        trigger = await call(ved_console, code="fixtureTick()")
        battery.info("watch_js.trigger", str(trigger)[:60], str(trigger))
        await asyncio.sleep(1.0)
        report = await call(ved_watch, collect=True, timeout=8)
        battery.info("watch_js.rep", report[:80].replace("\n", " "), report)
        return report

    await battery.step("watch_js", js_watch, has("TICK_"))

    # ---- 页面自开新标签的自动注册 ----
    async def popup() -> str:
        await call(ved_act, action="click", target="Popup")
        await asyncio.sleep(2.0)
        return await call(ved_tabs)

    await battery.step("auto_new_tab", popup,
                       lambda v: (str(v).count("[") >= 2, f"len={len(str(v))}"))

    # ---- close() 语义 ----
    targets_before = cdp_target_count(cdp_port)
    closed = await call(ved_close)
    await asyncio.sleep(1.0)
    targets_after = cdp_target_count(cdp_port)
    battery.info("close_semantics", f"CDP targets {targets_before} → {targets_after}", str(closed))
    return battery


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("launch", "attach"), required=True)
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_port}/index.html"
    app_js_url = f"http://127.0.0.1:{server.server_port}/app.js"
    tick_line = APP_JS[:APP_JS.index("return tickValue;")].count("\n") + 1

    output_dir = Path(tempfile.mkdtemp(prefix="veddata-parity-out-"))
    profile = Path(tempfile.mkdtemp(prefix="veddata-parity-profile-"))
    port = free_port()
    chrome_process = None

    os.environ["HEADLESS"] = "true"
    from veddata import paths

    paths.set_profile_dir(profile)
    paths.set_response_dir(output_dir)

    if args.mode == "attach":
        chrome_process = subprocess.Popen(
            [CHROME, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
             "--headless=new", "--no-first-run", "--no-default-browser-check"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        ready = False
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1).close()
                ready = True
                break
            except Exception:                                                  # noqa: BLE001
                time.sleep(0.25)
        os.environ["BROWSER_ADDRESS"] = f"http://127.0.0.1:{port}"
        print(f"[attach] 自起 Chrome pid={chrome_process.pid} cdp=127.0.0.1:{port} ready={ready}")
    else:
        os.environ.pop("BROWSER_ADDRESS", None)

    print(f"[{args.mode}] fixture={base_url}")
    print(f"[{args.mode}] profile={profile}")
    print(f"[{args.mode}] output={output_dir}")
    try:
        battery = await run_battery(base_url, app_js_url, tick_line, output_dir, port)
        path = Path(tempfile.gettempdir()) / f"veddata-parity-{args.mode}.json"
        path.write_text(json.dumps({"mode": args.mode, "profile": str(profile),
                                    "cdp_port": port if args.mode == "attach" else None,
                                    "results": battery.results},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
        passed = sum(1 for item in battery.results if item["ok"])
        print(f"[{args.mode}] {passed}/{len(battery.results)} PASS → {path}")
    finally:
        server.shutdown()
        if chrome_process is not None:
            alive = chrome_process.poll() is None
            print(f"[attach] ved_close() 之后我们起的 Chrome: {'仍存活' if alive else '已退出'}")
            chrome_process.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
