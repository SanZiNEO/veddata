"""Watch engine — batch observation of requests and JS breakpoints.

Not interactive debugging: 注册 N 个观测点 → 触发操作 → 所有观测点自动
记录值并继续执行（请求放行、断点自动 resume）→ 一次性取回快照。

- Request watch: page.route() 捕获但不拦截（记录后 continue_）。
- JS watch: CDP Debugger.setBreakpointByUrl，命中后提取作用域变量快照，
  然后 Debugger.resume 自动继续，不打乱页面执行流。

断点命中说明：
- 命中在函数体内 → local 作用域有函数的局部变量（"正在处理的数据"）。
- 命中在模块顶层 → module/script 作用域有模块级数据。
- 顶层初始化阶段帧的 url/line 可能未填充，从 breakpointId 解析回退。
"""

import asyncio
import re
import time


def _parse_breakpoint_id(bp_id: str) -> tuple[str, int]:
    """breakpointId 格式 `1:29:0:<url>` → (url, line)。解析失败返回 ("", 0)。"""
    parts = bp_id.split(":", 3)
    if len(parts) == 4:
        try:
            line = int(parts[1])
        except ValueError:
            line = 0
        return parts[3], line
    return "", 0


class WatchEngine:
    def __init__(self, page, cdp, registry):
        self._page = page
        self._cdp = cdp
        self._registry = registry            # ScriptRegistry（取断点处源码行）
        self._snapshots: list[dict] = []
        self._watch_breakpoints: dict[str, dict] = {}   # breakpointId → {watch_id, variables}
        self._watched_ids: set[str] = set()
        self._hit_ids: set[str] = set()
        self._done_event = asyncio.Event()
        self._routes: list = []              # 注册过的 pattern（clear 时 unroute）
        self._paused_handler_registered = False

    # ---- 观测点注册 ----

    async def add_request_watch(self, pattern: str, watch_id: str) -> None:
        """注册请求观测点：匹配 URL 的请求记录参数/头后放行。"""
        self._watched_ids.add(watch_id)

        if len(pattern) > 2 and pattern.startswith("/") and pattern.endswith("/"):
            url_pattern = re.compile(pattern[1:-1])
        else:
            url_pattern = pattern

        async def handler(route):
            req = route.request
            self._snapshots.append({
                "watch_id": watch_id,
                "type": "request",
                "url": req.url,
                "method": req.method,
                "headers": {k: v for k, v in dict(req.headers).items() if not k.startswith(":")},
                "timestamp": time.time(),
            })
            self._mark_hit(watch_id)
            await route.continue_()

        await self._page.route(url_pattern, handler)
        self._routes.append(url_pattern)

    async def add_js_watch(self, url: str, line: int, variables: list[str], watch_id: str) -> None:
        """注册 JS 观测点：代码行命中时记录指定变量的当前值，然后自动继续。"""
        self._watched_ids.add(watch_id)
        await self._cdp.send("Debugger.enable")
        await self._cdp.send("Runtime.enable")
        if not self._paused_handler_registered:
            self._cdp.on("Debugger.paused", lambda e: asyncio.create_task(self.on_debugger_paused(e)))
            self._paused_handler_registered = True
        bp = await self._cdp.send("Debugger.setBreakpointByUrl", {
            "url": url,
            "lineNumber": line,
        })
        bp_id = bp.get("breakpointId")
        if bp_id:
            self._watch_breakpoints[bp_id] = {
                "watch_id": watch_id,
                "variables": variables,
            }

    # ---- 断点命中 ----

    async def on_debugger_paused(self, event: dict) -> None:
        """断点命中：记录作用域变量快照后自动继续。

        任何异常都不能阻塞 resume —— 用 try/finally 保证页面放行；
        所有 CDP 调用限时 3 秒。
        """
        bp_id = (event.get("hitBreakpoints") or [None])[0]
        watch = self._watch_breakpoints.get(bp_id)
        if not watch:
            try:
                await asyncio.wait_for(self._cdp.send("Debugger.resume"), timeout=3.0)
            except Exception:
                pass
            return

        try:
            frames = event.get("callFrames") or []
            # 顶层初始化阶段帧 url/line 可能未填充，优先取有 url 的帧，否则从断点 id 解析
            frame = next((f for f in frames if f.get("url")), frames[0] if frames else {})
            bp_url, bp_line = _parse_breakpoint_id(bp_id) if bp_id else ("", 0)
            url = frame.get("url") or bp_url
            line_no = frame.get("lineNumber")
            if line_no is None:
                line_no = bp_line

            vars_snapshot: dict = {}
            wanted = watch["variables"]
            for scope in frame.get("scopeChain", []):
                scope_type = scope.get("type")
                # global 作用域变量太多，只取前 5 个；其余作用域按上限 10 个
                cap = 5 if scope_type == "global" else 10
                try:
                    obj = await asyncio.wait_for(
                        self._cdp.send("Runtime.getProperties", {
                            "objectId": scope["object"]["objectId"],
                        }),
                        timeout=3.0,
                    )
                except Exception:
                    continue
                for prop in obj.get("result", []):
                    name = prop.get("name")
                    if name in ("this", "arguments"):
                        continue
                    if wanted and name not in wanted:
                        continue
                    val = prop.get("value", {})
                    vars_snapshot[name] = val.get("value", val.get("description", "?"))
                    if len(vars_snapshot) >= cap:
                        break
                if len(vars_snapshot) >= cap:
                    break

            source_line = ""
            if self._registry and url:
                try:
                    # 源码行只是辅助信息，3 秒拿不到就跳过，绝不阻塞 resume
                    source = await asyncio.wait_for(
                        self._registry.get_source(url), timeout=3.0
                    )
                    if source:
                        lines = source.splitlines()
                        if 0 <= line_no < len(lines):
                            source_line = lines[line_no].strip()[:160]
                except Exception:
                    pass

            self._snapshots.append({
                "watch_id": watch["watch_id"],
                "type": "js",
                "url": url,
                "line": line_no,
                "source": source_line,
                "variables": vars_snapshot,
                "call_stack": self._format_stack(frames[:3]),
            })
            self._mark_hit(watch["watch_id"])
        finally:
            try:
                await asyncio.wait_for(
                    self._cdp.send("Debugger.resume"), timeout=3.0
                )
            except Exception:
                pass

    @staticmethod
    def _format_stack(frames: list) -> list[str]:
        out = []
        for f in frames:
            fn = f.get("functionName") or "(anonymous)"
            out.append(f"{fn} @ {f.get('url', '')}:{f.get('lineNumber', 0)}")
        return out

    # ---- 收集 ----

    def _mark_hit(self, watch_id: str) -> None:
        self._hit_ids.add(watch_id)
        if self._hit_ids >= self._watched_ids:
            self._done_event.set()

    async def wait_for_snapshots(self, timeout: float = 10.0) -> list[dict]:
        """等所有已注册观测点都触发过（或超时），返回快照列表。"""
        if self._hit_ids < self._watched_ids:
            try:
                await asyncio.wait_for(self._done_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
        return list(self._snapshots)

    def pending_count(self) -> int:
        return len(self._watched_ids) - len(self._hit_ids)

    def snapshot_count(self) -> int:
        return len(self._snapshots)

    async def clear(self) -> None:
        """移除全部观测点并清空快照。"""
        for bp_id in list(self._watch_breakpoints):
            try:
                await self._cdp.send("Debugger.removeBreakpoint", {"breakpointId": bp_id})
            except Exception:
                pass
        self._watch_breakpoints.clear()
        for pattern in self._routes:
            try:
                await self._page.unroute(pattern)
            except Exception:
                pass
        self._routes.clear()
        self._snapshots.clear()
        self._watched_ids.clear()
        self._hit_ids.clear()
        self._done_event = asyncio.Event()
