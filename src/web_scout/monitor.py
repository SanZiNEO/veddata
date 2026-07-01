"""Network monitor module — intercept XHR/Fetch requests, filter JSON APIs, dedup and query."""

import json
import re


def _leaf_count(obj: dict | list, depth: int = 0) -> int:
    """Recursively count leaf fields in a JSON structure."""
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
    """Truncate cookie values: keep first and last 15 chars if too long."""
    if len(cookie) <= max_len:
        return cookie
    return cookie[:15] + "..." + cookie[-15:]


def _truncate_body(body_str: str, max_len: int = 2000) -> str:
    """Truncate response body text."""
    if len(body_str) <= max_len:
        return body_str
    return body_str[:max_len] + "\n... (truncated)"


def _extract_path(url: str) -> str:
    """Extract URL path component (before '?')."""
    return url.split("?")[0]


class NetworkMonitor:
    """Intercept browser network requests, filter JSON APIs, deduplicate and query."""

    ALLOWED_RESOURCE_TYPES = frozenset({"XHR", "Fetch", "Script", "Document", "EventSource"})

    def __init__(self, tab):
        self.tab = tab
        self.api_records: list[dict] = []
        self.embedded_records: list[dict] = []
        self._next_id = 1

    def start(self):
        """Begin listening to all network requests (all resource types)."""
        self.tab.listen.start(res_type=True)

    def stop(self):
        """Stop listening. Clears the queue but does not affect stored records."""
        self.tab.listen.stop()

    def step(self, timeout: float = 2.0) -> list:
        """Step through captured packets using listen.steps().

        Returns a list of DataPacket objects that were stored as JSON APIs.
        """
        new_packets = []
        for batch in self.tab.listen.steps(timeout=timeout, gap=5):
            items = batch if isinstance(batch, list) else [batch]
            for packet in items:
                if self.filter_and_store(packet):
                    new_packets.append(packet)
        return new_packets

    def wait_new(self, timeout: float = 3.0) -> int:
        """Block until new JSON APIs are captured.

        Returns the number of newly captured API endpoints.
        """
        before = len(self.api_records)
        self.step(timeout=timeout)
        return len(self.api_records) - before

    def get_count_snapshot(self) -> dict:
        """Snapshot each API's hit count for later diff detection."""
        return {rec["path"]: rec["count"] for rec in self.api_records}

    def recurring_since(self, snapshot: dict) -> list[dict]:
        """Return records whose hit count increased since the snapshot."""
        recurring = []
        for rec in self.api_records:
            old_count = snapshot.get(rec["path"], 0)
            if rec["count"] > old_count:
                recurring.append(rec)
        return recurring

    def filter_and_store(self, packet) -> bool:
        """Check whether a packet is a JSON API and store it.

        Returns True if the packet was stored/updated.
        """
        if packet.is_failed:
            return False

        resource_type = getattr(packet, 'resourceType', 'Other')
        if resource_type not in self.ALLOWED_RESOURCE_TYPES:
            return False

        resp_headers = packet.response.headers
        content_type = resp_headers.get("content-type", "").lower()

        body = packet.response.body
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                if "application/json" not in content_type:
                    body = self._try_parse_jsonp(body)
                    if body is None:
                        return False
            else:
                pass
        elif isinstance(body, (dict, list)):
            pass
        else:
            return False

        url = packet.url
        method = packet.method
        path = _extract_path(url)

        headers = dict(packet.request.headers)

        params = {}
        if hasattr(packet.request, "params") and packet.request.params:
            params = dict(packet.request.params)

        post_data = None
        if hasattr(packet.request, "postData") and packet.request.postData:
            raw = packet.request.postData
            if isinstance(raw, str):
                try:
                    post_data = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    post_data = raw
            else:
                post_data = raw

        status = packet.response.status
        field_count = _leaf_count(body) if isinstance(body, (dict, list)) else 0
        response_url = getattr(packet.response, 'url', url)
        response_headers = dict(resp_headers)

        existing = None
        for rec in self.api_records:
            if rec["path"] == path and rec["method"] == method:
                existing = rec
                break

        if existing:
            existing["count"] += 1
            existing["request_headers"] = headers
            existing["request_params"] = params
            existing["request_body"] = post_data
            existing["response_status"] = status
            existing["response_body"] = body
            existing["field_count"] = field_count
            existing["resource_type"] = resource_type
            existing["response_url"] = response_url
            existing["response_headers"] = response_headers
        else:
            self.api_records.append(
                {
                    "id": self._next_id,
                    "url": url,
                    "path": path,
                    "method": method,
                    "count": 1,
                    "request_headers": headers,
                    "request_params": params,
                    "request_body": post_data,
                    "response_status": status,
                    "response_body": body,
                    "field_count": field_count,
                    "resource_type": resource_type,
                    "response_url": response_url,
                    "response_headers": response_headers,
                }
            )
            self._next_id += 1

        return True

    def list_apis(self, keyword: str | None = None) -> str:
        """Return a formatted list of captured API endpoints.

        Args:
            keyword: Optional filter — only show APIs whose path or response body
                contains this keyword (case-insensitive, recursive text search).

        Returns:
            Multi-line string listing API endpoints with ID, method, path, count, fields.
        """
        all_records = self.api_records + self.embedded_records
        if keyword:
            kw = keyword.lower()
            filtered = []
            for r in all_records:
                if kw in r["path"].lower():
                    filtered.append(r)
                    continue
                body_str = json.dumps(r.get("response_body", {}), ensure_ascii=False)
                if kw in body_str.lower():
                    filtered.append(r)
                    continue
            all_records = filtered

        if not all_records:
            return "No APIs captured yet."

        lines = []
        for rec in all_records:
            method = rec["method"]
            path = rec["path"]
            count = rec["count"]
            fields = rec["field_count"]
            rtype = rec.get("resource_type", "XHR")
            source = rec.get("source", "")

            tag_parts = []
            if source == "embedded":
                tag_parts.append("[SSR]")
            elif rtype == "Script":
                tag_parts.append("[JSONP]")
            elif rtype == "EventSource":
                tag_parts.append("[SSE]")
            tag = " ".join(tag_parts) + " " if tag_parts else ""

            lines.append(f"[{rec['id']}] {tag}{method} {path}  {count} {'times' if count > 1 else 'time'} → {fields} fields")
        return "\n".join(lines)

    def get_api(self, api_id: int, detail: str = "preview") -> str:
        """Return detailed request/response for a specific API endpoint.

        Args:
            api_id: Numeric ID of the API (1-based, from list_apis output).
            detail: "preview" (default) = truncated summary.
                    "full" = complete headers + full field structure.

        Returns:
            Formatted text with full request and response details.
        """
        record = self.get_record(api_id)
        if not record:
            return f"API #{api_id} not found."

        lines = []
        lines.append("=== Request ===")
        lines.append(f"URL:    {record['url']}")
        lines.append(f"Method: {record['method']}")

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
                val = headers.get(key)
                if val is not None:
                    if key == "Cookie":
                        val = _truncate_cookie(str(val))
                    lines.append(f"  {key}: {val}")

        params = record.get("request_params")
        if params:
            text = json.dumps(params, indent=2, ensure_ascii=False)
            lines.append(f"Params:\n{text}")

        body = record.get("request_body")
        if body:
            if isinstance(body, dict):
                text = json.dumps(body, indent=2, ensure_ascii=False)
            else:
                text = str(body)
            lines.append(f"Body:\n{text}")

        lines.append("")
        lines.append("=== Response ===")
        lines.append(f"Status: {record.get('response_status', '?')}")

        resp_body = record.get("response_body", {})

        if detail == "full":
            lines.append("Field structure:")
            lines.append(self._format_field_structure(resp_body))

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
                status = record.get("response_status", "?")
                lines.append("")
                lines.append("=== Redirect ===")
                lines.append(f"Request:  {request_url}")
                lines.append(f"Status:   {status}")
                lines.append(f"Response: {response_url}")
                location = resp_headers.get("Location", "")
                if location:
                    lines.append(f"Location: {location}")
        else:
            text = json.dumps(resp_body, indent=2, ensure_ascii=False)
            lines.append(f"Body (truncated):\n{_truncate_body(text)}")

        return "\n".join(lines)

    def find_context(self, keyword: str) -> list[dict]:
        """Search all captured data for keyword, returning field paths and values.

        Searches API response bodies, SSR embedded JSON, and page meta tags.
        Returns list of {source, field, value} dicts.
        """
        results = []
        kw = keyword.lower()
        all_records = self.api_records + self.embedded_records

        for rec in all_records:
            body = rec.get("response_body", {})
            matches = self._deep_search(body, kw, "")
            source = f"[API] {rec['method']} {rec['path']}"
            if rec.get("source") == "embedded":
                source = f"[SSR] window.{rec['key']}"
            for field_path, value in matches:
                results.append({"source": source, "field": field_path, "value": self._truncate_val(value, 300)})

        return results

    @staticmethod
    def _deep_search(obj, keyword: str, prefix: str = "") -> list[tuple[str, str]]:
        """Recursively search JSON for string values containing keyword."""
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

    @staticmethod
    def _truncate_val(val: str, max_len: int = 300) -> str:
        if len(val) <= max_len:
            return val
        return val[:max_len] + "..."

    def get_record(self, api_id: int) -> dict | None:
        """Return the raw record dict for a given API ID.

        Args:
            api_id: Numeric ID of the API.

        Returns:
            The record dict, or None if not found.
        """
        for rec in self.api_records:
            if rec["id"] == api_id:
                return rec
        for rec in self.embedded_records:
            if rec["id"] == api_id:
                return rec
        return None

    @staticmethod
    def _try_parse_jsonp(text: str) -> dict | None:
        """Try to extract JSON from JSONP callback wrapper like `callback({...})`."""
        import re
        m = re.match(r'^[a-zA-Z_$][\w$]*\s*\((.+)\)\s*;?\s*$', text.strip())
        if m:
            try:
                inner = m.group(1)
                return json.loads(inner)
            except (json.JSONDecodeError, ValueError):
                pass
        return None

    def capture_embedded_json(self) -> int:
        """Extract embedded JSON from window globals and <script> tags.

        Uses pattern-based discovery: scans window globals matching
        (STATE|DATA|INITIAL|PRELOAD|STORE|APP|NUXT|CONFIG) and tries to
        JSON-parse all <script> tag contents, regardless of type attribute."""
        self.embedded_records.clear()

        js = """
        (function() {
            var results = {};
            // 按命名规律通配扫描 window 全局变量
            var keys = Object.keys(window);
            var pattern = /(STATE|DATA|INITIAL|PRELOAD|STORE|APP|NUXT|CONFIG)/i;
            for (var i = 0; i < keys.length; i++) {
                var key = keys[i];
                if (key.length > 40) continue;
                if (!pattern.test(key)) continue;
                try {
                    var val = window[key];
                    if (val && typeof val === 'object' && !Array.isArray(val)) {
                        var size = Object.keys(val).length;
                        if (size >= 2) results[key] = val;
                    }
                } catch(e) {}
            }
            // 尝试解析所有 <script> 标签文本内容
            var scripts = document.getElementsByTagName('script');
            for (var j = 0; j < scripts.length; j++) {
                var s = scripts[j];
                var t = (s.type || '').toLowerCase();
                if (t && t.indexOf('javascript') !== -1 && t.indexOf('json') === -1) continue;
                var text = s.textContent.trim();
                if (!text || text.length < 20 || text.length > 200000) continue;
                // 快速排除 JS 代码: JSON 以 { 或 [ 开头
                var firstChar = text.charAt(0);
                if (firstChar !== '{' && firstChar !== '[') continue;
                var id = s.id || ('script_' + j);
                try { var parsed = JSON.parse(text); results[id] = parsed; } catch(e) {}
            }
            return JSON.stringify(results);
        })()
        """
        try:
            raw = self.tab.run_js(js)
            if not raw:
                return 0
            data = json.loads(raw)
        except (json.JSONDecodeError, Exception):
            return 0

        if not isinstance(data, dict):
            return 0

        for key, value in data.items():
            if value is None:
                continue
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, ValueError):
                    pass
            field_count = _leaf_count(value) if isinstance(value, (dict, list)) else 0
            self.embedded_records.append({
                "id": self._next_id,
                "source": "embedded",
                "key": key,
                "url": self.tab.url,
                "method": "SSR",
                "path": f"window.{key}",
                "count": 1,
                "request_headers": {},
                "request_params": {},
                "request_body": None,
                "response_status": 200,
                "response_body": value,
                "field_count": field_count,
                "resource_type": "Document",
                "response_url": self.tab.url,
                "response_headers": {},
            })
            self._next_id += 1

        return len(self.embedded_records)

    def _format_field_structure(self, obj, max_array_items: int = 3) -> str:
        """Format a JSON structure showing field names, types, and sample values."""
        lines = []

        def _walk(o, prefix: str = "", depth: int = 0):
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
