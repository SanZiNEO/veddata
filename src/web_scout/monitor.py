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

    def __init__(self, tab):
        self.tab = tab
        self.api_records: list[dict] = []
        self._next_id = 1

    def start(self):
        """Begin listening to all network requests."""
        self.tab.listen.start()

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

    def filter_and_store(self, packet) -> bool:
        """Check whether a packet is a JSON API and store it.

        Returns True if the packet was stored/updated.
        """
        if packet.is_failed:
            return False

        resp_headers = packet.response.headers
        content_type = resp_headers.get("content-type", "")
        if "application/json" not in content_type:
            return False

        body = packet.response.body
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                return False
        elif not isinstance(body, dict):
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
        field_count = _leaf_count(body)

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
        records = self.api_records
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
            method = rec["method"]
            path = rec["path"]
            count = rec["count"]
            fields = rec["field_count"]
            lines.append(f"[{rec['id']}] {method} {path}  {count} {'times' if count > 1 else 'time'} → {fields} fields")
        return "\n".join(lines)

    def get_api(self, api_id: int) -> str:
        """Return detailed request/response for a specific API endpoint.

        Args:
            api_id: Numeric ID of the API (1-based, from list_apis output).

        Returns:
            Formatted text with full request and response details.
        """
        record = None
        for rec in self.api_records:
            if rec["id"] == api_id:
                record = rec
                break

        if not record:
            return f"API #{api_id} not found."

        lines = []
        lines.append("=== Request ===")
        lines.append(f"URL:    {record['url']}")
        lines.append(f"Method: {record['method']}")

        headers = record.get("request_headers", {})
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
        text = json.dumps(resp_body, indent=2, ensure_ascii=False)
        lines.append(f"Body (truncated):\n{_truncate_body(text)}")

        return "\n".join(lines)

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
        return None
