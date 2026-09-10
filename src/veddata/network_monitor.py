"""Network monitor — event-driven capture of page data sources.

Replaces the old polling NetworkPool.  Attaches to a Playwright Page via
page.on("request"/"response"/"websocket").  Records carry factual fields
(source / trigger / structure) and NO resourceType category labels.

Records are deduplicated by (path, method, tab_id); repeat hits bump
`count` and refresh request/response fields — ved_act's new-API diff
and count_snapshot()/recurring_since() depend on this.
"""

import asyncio
import json
import re
import time
from urllib.parse import parse_qs


def _try_parse_jsonp(text: str) -> dict | None:
    m = re.match(r'^[a-zA-Z_$][\w$]*\s*\((.+)\)\s*;?\s*$', text.strip())
    if m:
        try:
            inner = m.group(1)
            return json.loads(inner)
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _leaf_count(obj, depth: int = 0) -> int:
    if depth > 8:
        return 0
    count = 0
    if isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, (dict, list)):
                count += _leaf_count(v, depth + 1)
            else:
                count += 1
    elif isinstance(obj, list):
        for item in obj:
            count += _leaf_count(item, depth + 1)
    return count


def _truncate_cookie(cookie: str, max_len: int = 30) -> str:
    if len(cookie) <= max_len:
        return cookie
    return cookie[:15] + "..." + cookie[-15:]


def _truncate_body(body_str: str, max_len: int = 2000) -> str:
    if len(body_str) <= max_len:
        return body_str
    return body_str[:max_len] + "\n... (truncated)"


def _get_header(headers: dict, name: str) -> str | None:
    """Case-insensitive header lookup (Playwright lower-cases header names)."""
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return None


class NetworkMonitor:
    """Event-driven capture pool for API records, keyed by CDP tab_id."""

    INTERESTING_RESOURCE_TYPES = frozenset({"xhr", "fetch", "document", "eventsource"})

    def __init__(self):
        self.api_records: list[dict] = []
        self._next_id = 1
        self._pending_request: dict[str, dict] = {}   # url → {method, timestamp}
        self._current_trigger: str = "page_load"
        self._page_to_tab = None                      # Callable[[Page], str]
        self._page = None                             # attach 时的 page（frame 取不到时回退）

    # ---- 事件挂接 ----

    def attach(self, page, page_to_tab) -> None:
        """Bind to a Page's events.  Handlers are sync; async work is
        dispatched via asyncio.create_task."""
        self._page = page
        self._page_to_tab = page_to_tab
        page.on("request", self._on_request)
        page.on("response", self._on_response)
        page.on("websocket", self._on_websocket)

    def _on_request(self, request) -> None:
        if request.resource_type in self.INTERESTING_RESOURCE_TYPES:
            self._pending_request[request.url] = {
                "method": request.method,
                "timestamp": time.time(),
            }

    def _on_response(self, response) -> None:
        asyncio.create_task(self._handle_response(response))

    async def _handle_response(self, response) -> None:
        request = response.request
        tab_id = self._tab_id_of(request)
        if tab_id is None:
            return

        ct = response.headers.get("content-type", "")
        if "json" not in ct and "text/html" not in ct:
            return

        body = None
        try:
            body = await response.json()
        except Exception:
            try:
                text = await response.text()
            except Exception:
                return
            body = _try_parse_jsonp(text)
            if body is None:
                return
        if not isinstance(body, (dict, list)):
            return

        req_info = self._pending_request.pop(response.url, {})
        path = response.url.split("?")[0]
        params = {}
        qs = parse_qs(response.url.partition("?")[2])
        for k, v in qs.items():
            params[k] = v[0] if len(v) == 1 else v

        request_body = None
        try:
            request_body = request.post_data_json
        except Exception:
            request_body = None
        if request_body is None:
            request_body = request.post_data

        try:
            raw_headers = await request.all_headers()
            # HTTP/2 伪头（:authority / :method / :path / :scheme）不能当普通 header 用：
            # httpx 会直接拒收（Illegal header name），重放请求就废了。
            request_headers = {k: v for k, v in (raw_headers or {}).items() if not k.startswith(":")}
        except Exception:
            request_headers = {}

        record = {
            "url": response.url,
            "path": path,
            "method": req_info.get("method", request.method),
            "count": 1,
            "request_headers": request_headers,
            "request_params": params,
            "request_body": request_body,
            "response_status": response.status,
            "response_body": body,
            "field_count": _leaf_count(body),
            "response_url": response.url,
            "response_headers": dict(response.headers),
            "source": response.url,
            "trigger": self._current_trigger,
            "timestamp": req_info.get("timestamp", time.time()),
        }

        existing = None
        for rec in self.api_records:
            if rec["path"] == path and rec["method"] == record["method"] and rec["tab_id"] == tab_id:
                existing = rec
                break

        if existing:
            existing["count"] += 1
            existing["request_headers"] = record["request_headers"]
            existing["request_params"] = record["request_params"]
            existing["request_body"] = record["request_body"]
            existing["response_status"] = record["response_status"]
            existing["response_body"] = record["response_body"]
            existing["field_count"] = record["field_count"]
            existing["response_url"] = record["response_url"]
            existing["response_headers"] = record["response_headers"]
            existing["source"] = record["source"]
            existing["trigger"] = record["trigger"]
            existing["timestamp"] = record["timestamp"]
        else:
            record["id"] = self._next_id
            record["tab_id"] = tab_id
            self.api_records.append(record)
            self._next_id += 1

    def _tab_id_of(self, request) -> str | None:
        """Resolve a request to our tab_id.

        官方文档：导航早期 / Service Worker 请求取不到 request.frame 会抛异常，
        此时回退到 attach 时保存的 page。仍失败返回 None（记录不入库）。
        """
        try:
            return self._page_to_tab(request.frame.page)
        except Exception:
            try:
                return self._page_to_tab(self._page) if self._page else None
            except Exception:
                return None

    def _on_websocket(self, ws) -> None:
        asyncio.create_task(self._handle_ws(ws))

    async def _handle_ws(self, ws) -> None:
        try:
            tab_id = self._page_to_tab(ws.page)
        except Exception:
            tab_id = self._page_to_tab(self._page) if self._page else ""
        url = ws.url
        path = url.split("?")[0]

        existing = None
        for rec in self.api_records:
            if rec["path"] == path and rec["method"] == "-" and rec["tab_id"] == tab_id:
                existing = rec
                break

        if existing:
            existing["count"] += 1
        else:
            self.api_records.append({
                "id": self._next_id,
                "tab_id": tab_id,
                "url": url,
                "path": path,
                "method": "-",
                "count": 1,
                "request_headers": {},
                "request_params": {},
                "request_body": None,
                "response_status": 0,
                "response_body": {},
                "field_count": 0,
                "response_url": url,
                "response_headers": {},
                "source": url,
                "trigger": self._current_trigger,
                "timestamp": time.time(),
                "ws_messages": [],
            })
            self._next_id += 1

        record = existing or self.api_records[-1]

        def on_frame_received(payload):
            self._append_ws_message(record, "in", payload)

        def on_frame_sent(payload):
            self._append_ws_message(record, "out", payload)

        ws.on("framereceived", on_frame_received)
        ws.on("framesent", on_frame_sent)

    @staticmethod
    def _append_ws_message(record: dict, direction: str, payload) -> None:
        record["ws_messages"].append({
            "time": round(time.time(), 3),
            "dir": direction,
            "data": str(payload)[:2000],
        })
        if len(record["ws_messages"]) > 50:
            del record["ws_messages"][0]

    # ---- 内嵌数据扫描 ----

    async def scan_embedded(self, page) -> int:
        """扫一遍页面，找所有内嵌数据（script JSON 块 + window.__xxx__ 全局变量）。

        记录并入 api_records，去重键 (path, method="-")，重复扫描只 bump count。
        返回新增条数。
        """
        added = 0
        try:
            tab_id = self._page_to_tab(page) if self._page_to_tab else ""
        except Exception:
            tab_id = ""

        # 1. <script> 里的 JSON 块
        scripts = await page.evaluate("""
        () => {
          const r = [];
          for (const s of document.querySelectorAll('script:not([src])')) {
            const t = (s.textContent || '').trim();
            if (!t) continue;
            try { const p = JSON.parse(t); r.push({id: s.id || '', body: p}); }
            catch(e) {}
          }
          return r;
        }
        """)
        for item in scripts or []:
            source = f"<script id='{item['id']}'>" if item.get("id") else "<script>"
            added += self._store_embedded(
                tab_id, source, item.get("body", {}), "html_parse"
            )

        # 2. window.__xxx__ 全局变量（上限 50 个）
        keys = await page.evaluate(
            "Object.keys(window).filter(k => k.startsWith('__')).slice(0, 50)"
        ) or []
        for k in keys:
            try:
                val = await page.evaluate(
                    "(k) => { const v = window[k]; "
                    "return {t: typeof v, s: (typeof v === 'object' && v !== null) "
                    "? JSON.stringify(v).slice(0, 2000) : String(v).slice(0, 2000)} }",
                    k,
                )
            except Exception:
                continue
            added += self._store_embedded(
                tab_id,
                f"window.{k}",
                {"type": val.get("t", ""), "sample": val.get("s", "")},
                "js_global",
            )
        return added

    def _store_embedded(self, tab_id: str, source: str, body, trigger: str) -> int:
        path = source
        existing = None
        for rec in self.api_records:
            if rec["path"] == path and rec["method"] == "-" and rec["tab_id"] == tab_id:
                existing = rec
                break
        if existing:
            existing["count"] += 1
            existing["response_body"] = body
            existing["field_count"] = _leaf_count(body)
            existing["trigger"] = trigger
            return 0
        self.api_records.append({
            "id": self._next_id,
            "tab_id": tab_id,
            "url": source,
            "path": path,
            "method": "-",
            "count": 1,
            "request_headers": {},
            "request_params": {},
            "request_body": None,
            "response_status": 0,
            "response_body": body,
            "field_count": _leaf_count(body),
            "response_url": source,
            "response_headers": {},
            "source": source,
            "trigger": trigger,
            "timestamp": time.time(),
        })
        self._next_id += 1
        return 1

    # ---- 触发上下文 ----

    def set_trigger_context(self, desc: str) -> None:
        self._current_trigger = desc

    def reset_trigger(self) -> None:
        self._current_trigger = "page_load"

    # ---- 查询（从 network_pool.py 平移） ----

    def get_by_tab(self, tab_id: str) -> list[dict]:
        if not tab_id:
            return self.api_records
        return [r for r in self.api_records if r["tab_id"] == tab_id]

    def get_record(self, api_id: int, tab_id: str = "") -> dict | None:
        records = self.get_by_tab(tab_id) if tab_id else self.api_records
        for rec in records:
            if rec["id"] == api_id:
                return rec
        return None

    def prune(self, tab_id: str):
        self.api_records = [r for r in self.api_records if r["tab_id"] != tab_id]

    def prune_all(self):
        self.api_records.clear()
        self._next_id = 1

    def list_apis(self, keyword: str | None = None, tab_id: str = "") -> str:
        records = self.get_by_tab(tab_id)
        if keyword:
            kw = keyword.lower()
            filtered = []
            for r in records:
                if kw in r["path"].lower():
                    filtered.append(r)
                    continue
                body_str = json.dumps(r.get("response_body", {}), ensure_ascii=False)
                if kw in body_str.lower():
                    filtered.append(r)
                    continue
            records = filtered
        if not records:
            return "No APIs captured yet."
        lines = []
        for rec in records:
            lines.append(
                f"[{rec['id']}] {rec['method']} {rec['path']}  "
                f"{rec['count']} {'times' if rec['count'] > 1 else 'time'} → {rec['field_count']} fields"
            )
        return "\n".join(lines)

    def inspect(self, api_id: int, detail: str = "preview", tab_id: str = "") -> str:
        record = self.get_record(api_id, tab_id)
        if not record:
            return f"API #{api_id} not found."
        return _format_inspect(record, detail)

    def find_context(self, keyword: str, tab_id: str = "") -> list[dict]:
        results = []
        kw = keyword.lower()
        records = self.get_by_tab(tab_id)
        for rec in records:
            body = rec.get("response_body", {})
            matches = self._deep_search(body, kw, "")
            source = f"[API] {rec['method']} {rec['path']}"
            for field_path, value in matches:
                results.append({
                    "source": source,
                    "field": field_path,
                    "value": value[:300] + ("..." if len(value) > 300 else ""),
                })
        return results

    @staticmethod
    def _deep_search(obj, keyword: str, prefix: str = "") -> list[tuple[str, str]]:
        results = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                full = f"{prefix}.{k}" if prefix else k
                if isinstance(v, str) and keyword in v.lower():
                    results.append((full, v))
                elif isinstance(v, (dict, list)):
                    results.extend(NetworkMonitor._deep_search(v, keyword, full))
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                full = f"{prefix}[{i}]"
                if isinstance(item, str) and keyword in item.lower():
                    results.append((full, item))
                elif isinstance(item, (dict, list)):
                    results.extend(NetworkMonitor._deep_search(item, keyword, full))
        return results

    def count_snapshot(self) -> dict:
        return {r["path"]: r["count"] for r in self.api_records}

    def recurring_since(self, snapshot: dict) -> list[dict]:
        return [r for r in self.api_records if r["count"] > snapshot.get(r["path"], 0)]


def _format_inspect(record: dict, detail: str = "preview") -> str:
    lines = []
    lines.append("=== Request ===")
    lines.append(f"URL:    {record['url']}")
    lines.append(f"Method: {record['method']}")
    trigger = record.get("trigger")
    if trigger:
        lines.append(f"Trigger: {trigger}")

    headers = record.get("request_headers", {})
    if detail == "full":
        lines.append("Headers (all):")
        for k, v in headers.items():
            if k.lower() == "cookie":
                v = _truncate_cookie(str(v))
            lines.append(f"  {k}: {v}")
    else:
        lines.append("Headers:")
        for key in ("Content-Type", "Referer", "Cookie", "User-Agent", "Origin", "X-Requested-With"):
            val = _get_header(headers, key)
            if val is not None:
                if key.lower() == "cookie":
                    val = _truncate_cookie(str(val))
                lines.append(f"  {key}: {val}")

    params = record.get("request_params")
    if params:
        text = json.dumps(params, indent=2, ensure_ascii=False)
        lines.append(f"Params:\n{text}")

    body = record.get("request_body")
    if body:
        text = json.dumps(body, indent=2, ensure_ascii=False) if isinstance(body, dict) else str(body)
        lines.append(f"Body:\n{text}")

    ws_messages = record.get("ws_messages")
    if ws_messages:
        lines.append("")
        lines.append("=== WebSocket Messages (recent) ===")
        for m in ws_messages[-5:]:
            lines.append(f"  [{m['time']}] {m['dir']}: {m['data'][:200]}")

    lines.append("")
    lines.append("=== Response ===")
    lines.append(f"Status: {record.get('response_status', '?')}")

    resp_body = record.get("response_body", {})
    if detail == "full":
        lines.append("Field structure:")
        lines.append(_format_field_structure(resp_body))
        resp_headers = record.get("response_headers", {})
        if resp_headers:
            lines.append("")
            lines.append("=== Response Headers ===")
            for k, v in resp_headers.items():
                if k.lower() == "set-cookie":
                    v = _truncate_cookie(str(v)[:50])
                lines.append(f"  {k}: {v}")
        request_url = record.get("url", "")
        response_url = record.get("response_url", "")
        if response_url and response_url != request_url:
            lines.append("")
            lines.append("=== Redirect ===")
            lines.append(f"Request:  {request_url}")
            lines.append(f"Status:   {record.get('response_status', '?')}")
            lines.append(f"Response: {response_url}")
            location = _get_header(resp_headers, "Location")
            if location:
                lines.append(f"Location: {location}")
    else:
        text = json.dumps(resp_body, indent=2, ensure_ascii=False)
        lines.append(f"Body (truncated):\n{_truncate_body(text)}")

    return "\n".join(lines)


def _format_field_structure(obj, max_array_items: int = 3) -> str:
    lines = []
    def _walk(o, prefix="", depth=0):
        if depth > 6:
            return
        indent = "  " * depth
        if isinstance(o, dict):
            for k, v in o.items():
                full_key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    lines.append(f"{indent}{full_key}: {{object}} — {len(v)} keys")
                    if depth < 3:
                        _walk(v, full_key, depth + 1)
                elif isinstance(v, list):
                    count = len(v)
                    if count > 0 and isinstance(v[0], dict):
                        lines.append(f"{indent}{full_key}: [{count}] — first item fields:")
                        _walk(v[0], "", depth + 1)
                    elif count > 0:
                        sample = str(v[:max_array_items])[:60]
                        lines.append(f"{indent}{full_key}: [{count}] — sample: {sample}")
                    else:
                        lines.append(f"{indent}{full_key}: [] (empty)")
                else:
                    t = type(v).__name__
                    s = str(v)[:50]
                    lines.append(f"{indent}{full_key}: {t} = {s}")
        elif isinstance(o, list) and len(o) > 0 and isinstance(o[0], dict):
            lines.append(f"{indent}{prefix}: [{len(o)}] — first item fields:")
            _walk(o[0], "", depth + 1)
    _walk(obj)
    return "\n".join(lines)
