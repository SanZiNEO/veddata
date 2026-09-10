"""Watch engine — batch observation of requests and JS breakpoints.

不是交互式调试：注册 N 个观测点 → 触发操作 → 每个点自动记录值并放行
（请求 continue_、断点 resume）→ 一次性取回快照。

两类观测点
----------
- **Request watch**：``page.route()`` 捕获但不拦截（记录参数/头后 ``continue_``）。
- **JS watch**：CDP ``Debugger.setBreakpointByUrl``，命中后提取作用域变量快照，
  然后 ``Debugger.resume`` 自动继续 —— 和人工断点是同一个接口，区别只在"命中后自动放行"。

边界（防止把内存或页面搞垮）
----------------------------
- 每个观测点有 ``max_hits``（默认 1）：**达到后自动移除该点** —— 断点打在热点行也不会
  被反复中断，内存也不会无界增长；``max_hits=0`` 表示不限，但受下面的全局上限兜底。
- 单点快照上限 ``MAX_PER_WATCH``、总快照上限 ``MAX_TOTAL``，超出丢最旧的。
- 行号对外统一 **1-based**（与 ``ved_script_source`` 显示的一致），内部转成 CDP 的 0-based。

观测点 id
---------
每个点都有 id：调用方可用 ``{"id": "login"}`` 自定义，缺省自动分配 ``w1``/``w2``…，
**单调递增、跨批次不重复**，方便列表与删除。
"""

import asyncio
import re
import time

DEFAULT_MAX_HITS = 1
MAX_PER_WATCH = 20
MAX_TOTAL = 200


def _parse_breakpoint_id(bp_id: str) -> tuple[str, int]:
    """breakpointId 格式 `1:29:0:<url>` → (url, line)。解析失败返回 ("", 0)。

    注意：这里的 line 是 CDP 的 **0-based** 行号。
    """
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
        self._watches: dict[str, dict] = {}   # watch_id → 观测点描述
        self._breakpoints: dict[str, str] = {}  # watch_id → breakpointId
        self._routes: dict[str, object] = {}    # watch_id → 已注册的 url pattern
        self._hit_ids: set[str] = set()
        self._done_event = asyncio.Event()
        self._paused_handler_registered = False
        self._seq = 0

    # ---- 观测点 id / 列表 ----

    def alloc_id(self) -> str:
        """自动分配 id（单调递增，跨批次不重复）。"""
        self._seq += 1
        return f"w{self._seq}"

    def watch_ids(self) -> list[str]:
        return list(self._watches)

    def list_watches(self) -> str:
        if not self._watches:
            return "No watches registered."
        lines = [f"Watches ({len(self._watches)}):"]
        for watch in self._watches.values():
            state = "watching" if watch["state"] == "watching" else "done"
            head = f"  {watch['id']}  {watch['type']:<7} {watch['target']}"
            limit = watch["max_hits"] or "∞"
            tail = f"  hits={watch['hits']}/{limit}  {state}"
            if watch.get("variables"):
                tail += f"  vars={','.join(watch['variables'])}"
            lines.append(head + tail)
        lines.append(f"snapshots: {len(self._snapshots)}")
        lines.append("(删除：ved_watch(remove='w1,w2')；全部删除：remove='all')")
        return "\n".join(lines)

    # ---- 观测点注册 ----

    async def add_request_watch(self, pattern: str, watch_id: str, max_hits: int = DEFAULT_MAX_HITS) -> None:
        """注册请求观测点：匹配 URL 的请求记录后放行（不拦截、不改写）。"""
        self._done_event.clear()            # 有新点要等，旧的事件不能复用
        url_pattern = self._compile(pattern)

        async def handler(route):
            req = route.request
            self._record({
                "watch_id": watch_id,
                "type": "request",
                "url": req.url,
                "method": req.method,
                "headers": {k: v for k, v in dict(req.headers).items() if not k.startswith(":")},
                "timestamp": time.time(),
            }, watch_id)
            await route.continue_()

        await self._page.route(url_pattern, handler)
        self._routes[watch_id] = url_pattern
        self._watches[watch_id] = {
            "id": watch_id,
            "type": "request",
            "target": pattern,
            "max_hits": max_hits,
            "hits": 0,
            "state": "watching",
        }

    async def add_js_watch(
        self,
        url: str,
        line: int,
        variables: list[str],
        watch_id: str,
        max_hits: int = DEFAULT_MAX_HITS,
    ) -> None:
        """注册 JS 观测点：代码行命中时记录指定变量值，然后自动继续。

        ``line`` 是 **1-based**（与 ved_script_source 显示的一致）。
        """
        self._done_event.clear()
        await self._cdp.send("Debugger.enable")
        await self._cdp.send("Runtime.enable")
        if not self._paused_handler_registered:
            self._cdp.on("Debugger.paused", lambda e: asyncio.create_task(self.on_debugger_paused(e)))
            self._paused_handler_registered = True

        cdp_line = max(0, int(line) - 1)     # 对外 1-based → CDP 0-based
        bp = await self._cdp.send("Debugger.setBreakpointByUrl", {
            "url": url,
            "lineNumber": cdp_line,
        })
        bp_id = bp.get("breakpointId", "")
        if bp_id:
            self._breakpoints[watch_id] = bp_id
        self._watches[watch_id] = {
            "id": watch_id,
            "type": "js",
            "target": f"{url}:{line}",
            "line": line,
            "variables": variables,
            "max_hits": max_hits,
            "hits": 0,
            "state": "watching",
        }

    @staticmethod
    def _compile(pattern: str):
        if len(pattern) > 2 and pattern.startswith("/") and pattern.endswith("/"):
            return re.compile(pattern[1:-1])
        return pattern

    # ---- 记录 / 退役 ----

    def _record(self, snapshot: dict, watch_id: str) -> None:
        """记一条快照并执行各层上限；达到 max_hits 就自动摘掉这个点。"""
        watch = self._watches.get(watch_id)
        if watch is None:
            return
        watch["hits"] += 1
        self._snapshots.append(snapshot)

        # 单点上限：丢该点最旧的
        while sum(1 for s in self._snapshots if s.get("watch_id") == watch_id) > MAX_PER_WATCH:
            for i, s in enumerate(self._snapshots):
                if s.get("watch_id") == watch_id:
                    del self._snapshots[i]
                    break
        # 总量上限：丢最旧的
        while len(self._snapshots) > MAX_TOTAL:
            self._snapshots.pop(0)

        limit = watch.get("max_hits") or 0
        if limit and watch["hits"] >= limit:
            asyncio.create_task(self._retire(watch_id))
        self._mark_hit(watch_id)

    async def _detach(self, watch_id: str) -> None:
        """摘掉 CDP 断点与 route（幂等，可重复调用）。"""
        bp_id = self._breakpoints.pop(watch_id, None)
        if bp_id:
            try:
                await self._cdp.send("Debugger.removeBreakpoint", {"breakpointId": bp_id})
            except Exception:
                pass
        pattern = self._routes.pop(watch_id, None)
        if pattern is not None:
            try:
                await self._page.unroute(pattern)
            except Exception:
                pass

    async def _retire(self, watch_id: str) -> None:
        """达到 max_hits：标记 done 并停止拦截（保留条目与快照，便于列表查看）。"""
        watch = self._watches.get(watch_id)
        if watch is None or watch.get("state") != "watching":
            return
        watch["state"] = "done"
        await self._detach(watch_id)

    async def remove(self, watch_id: str) -> bool:
        """删除一个观测点（连同它的快照）。返回是否存在。"""
        if watch_id not in self._watches:
            return False
        await self._detach(watch_id)
        self._watches.pop(watch_id, None)
        self._snapshots[:] = [s for s in self._snapshots if s.get("watch_id") != watch_id]
        self._hit_ids.discard(watch_id)
        self._sync_done_event()
        return True

    # ---- 断点命中 ----

    async def on_debugger_paused(self, event: dict) -> None:
        """断点命中：记录作用域变量快照后自动继续。

        任何异常都不能阻塞 resume —— 用 try/finally 保证页面放行；
        所有 CDP 调用限时 3 秒。
        """
        bp_id = (event.get("hitBreakpoints") or [None])[0]
        watch = self._watch_of_breakpoint(bp_id)
        if watch is None:
            await self._resume()
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

            self._record({
                "watch_id": watch["id"],
                "type": "js",
                "url": url,
                "line": line_no + 1,          # 对外统一 1-based
                "source": source_line,
                "variables": vars_snapshot,
                "call_stack": self._format_stack(frames[:3]),
            }, watch["id"])
        finally:
            await self._resume()

    async def _resume(self) -> None:
        try:
            await asyncio.wait_for(self._cdp.send("Debugger.resume"), timeout=3.0)
        except Exception:
            pass

    def _watch_of_breakpoint(self, bp_id: str | None) -> dict | None:
        """breakpointId → 观测点。用 breakpointId 反查，避免 id 复用带来的串味。"""
        if not bp_id:
            return None
        for watch_id, stored in self._breakpoints.items():
            if stored == bp_id:
                watch = self._watches.get(watch_id)
                if watch is not None:
                    return watch
        return None

    @staticmethod
    def _format_stack(frames: list) -> list[str]:
        out = []
        for f in frames:
            fn = f.get("functionName") or "(anonymous)"
            out.append(f"{fn} @ {f.get('url', '')}:{f.get('lineNumber', 0) + 1}")
        return out

    # ---- 收集 ----

    def _mark_hit(self, watch_id: str) -> None:
        self._hit_ids.add(watch_id)
        self._sync_done_event()

    def _sync_done_event(self) -> None:
        """所有观测点都至少命中过一次 → 放行等待者。"""
        if self._watches and set(self._watches) <= self._hit_ids:
            self._done_event.set()

    async def wait_for_snapshots(self, timeout: float = 10.0) -> list[dict]:
        """等所有已注册观测点都触发过（或超时），返回快照列表。"""
        if not (self._watches and set(self._watches) <= self._hit_ids):
            try:
                await asyncio.wait_for(self._done_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
        return list(self._snapshots)

    def pending_count(self) -> int:
        """还没命中过的观测点数。"""
        return sum(1 for w in self._watches.values() if w["hits"] == 0)

    def snapshot_count(self) -> int:
        return len(self._snapshots)

    async def clear(self) -> None:
        """移除全部观测点并清空快照（seq 不回退，id 不会复用）。"""
        for watch_id in list(self._watches):
            await self._detach(watch_id)
        self._watches.clear()
        self._snapshots.clear()
        self._hit_ids.clear()
        self._done_event = asyncio.Event()
