"""Network pool — shared API data store, listeners stay per-tab.

Each tab has its own tab.listen.start().  The pool just stores records
from all tabs in one list, each tagged by pkt.tab_id so callers can
filter by tab.
"""

import json
import re
import time


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


class NetworkPool:
    """Shared data pool for API records, keyed by CDP tab_id.

    Listeners are managed per-tab (tab.listen.start/res_type=True).
    The pool stores records from all tabs — call get_by_tab() to filter.
    """

    ALLOWED_RESOURCE_TYPES = frozenset({"XHR", "Fetch", "Script", "Document", "EventSource"})

    def __init__(self):
        self.api_records: list[dict] = []
        self._next_id = 1

    def start_tab(self, tab) -> None:
        """Start the CDP listener on a single tab."""
        tab.listen.start(res_type=True)

    def step(self, timeout: float = 2.0, tab=None) -> int:
        """Drain the listener queue.

        If tab is given, drain that specific tab's listener.
        Otherwise no-op (legacy compatibility).

        Returns count of newly stored records.
        """
        if not tab:
            return 0
        new_count = 0
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                pkt = tab.listen.wait(timeout=0.5)
            except Exception:
                pkt = None
            if not pkt:
                break
            if self.filter_and_store(pkt):
                new_count += 1
        return new_count

    def filter_and_store(self, pkt) -> bool:
        """Check if a DataPacket is a JSON API and store it.

        Returns True when stored/updated.
        """
        if pkt.is_failed:
            return False

        resource_type = getattr(pkt, 'resourceType', 'Other')
        if resource_type not in self.ALLOWED_RESOURCE_TYPES:
            return False

        tab_id = pkt.tab_id
        if not tab_id:
            return False

        resp_headers = pkt.response.headers
        content_type = resp_headers.get("content-type", "").lower()
        body = pkt.response.body

        if isinstance(body, str):
            try:
                body = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                if "application/json" not in content_type:
                    body = _try_parse_jsonp(body)
                    if body is None:
                        return False
        elif not isinstance(body, (dict, list)):
            return False

        url = pkt.url
        method = pkt.method
        path = url.split("?")[0]
        status = pkt.response.status
        field_count = _leaf_count(body) if isinstance(body, (dict, list)) else 0

        headers = dict(pkt.request.headers)
        params = {}
        if hasattr(pkt.request, "params") and pkt.request.params:
            params = dict(pkt.request.params)
        post_data = None
        if hasattr(pkt.request, "postData") and pkt.request.postData:
            raw = pkt.request.postData
            if isinstance(raw, str):
                try:
                    post_data = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    post_data = raw
            else:
                post_data = raw
        response_url = getattr(pkt.response, 'url', url)
        response_headers = dict(resp_headers)

        existing = None
        for rec in self.api_records:
            if rec["path"] == path and rec["method"] == method and rec["tab_id"] == tab_id:
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
            self.api_records.append({
                "id": self._next_id,
                "tab_id": tab_id,
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
            })
            self._next_id += 1

        return True

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
                    results.extend(NetworkPool._deep_search(v, keyword, full))
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                full = f"{prefix}[{i}]"
                if isinstance(item, str) and keyword in item.lower():
                    results.append((full, item))
                elif isinstance(item, (dict, list)):
                    results.extend(NetworkPool._deep_search(item, keyword, full))
        return results

    def count_snapshot(self) -> dict:
        return {r["path"]: r["count"] for r in self.api_records}

    def recurring_since(self, snapshot: dict) -> list[dict]:
        return [r for r in self.api_records if r["count"] > snapshot.get(r["path"], 0)]


def _truncate_cookie(cookie: str, max_len: int = 30) -> str:
    if len(cookie) <= max_len:
        return cookie
    return cookie[:15] + "..." + cookie[-15:]


def _truncate_body(body_str: str, max_len: int = 2000) -> str:
    if len(body_str) <= max_len:
        return body_str
    return body_str[:max_len] + "\n... (truncated)"


def _format_inspect(record: dict, detail: str = "preview") -> str:
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
        text = json.dumps(body, indent=2, ensure_ascii=False) if isinstance(body, dict) else str(body)
        lines.append(f"Body:\n{text}")

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
            location = resp_headers.get("Location", "")
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
