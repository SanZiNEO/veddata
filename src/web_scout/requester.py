"""Request executor — send HTTP requests via SessionPage with cookie sync."""

import json
import time

from DrissionPage import SessionPage


def exec_request(
    record: dict,
    override_params: str = "",
    override_body: str = "",
    override_headers: str = "",
    tab_id: str = "",
) -> str:
    """Execute an HTTP request against a record or custom URL.

    Args:
        record: Dict with at least 'url' and 'method'. Optionally headers/params/body.
        override_params: JSON string of params to override.
        override_body: JSON string of body to override.
        override_headers: JSON string of headers to override.
        tab_id: CDP tab ID for cookie sync.

    Returns:
        Formatted response string.
    """
    page = SessionPage()

    from web_scout import state
    if tab_id and state._browser:
        try:
            tab_obj = state._browser.get_tab_by_id(tab_id)
            if tab_obj:
                cookies_list = tab_obj.cookies(all_domains=False, all_info=False)
                if cookies_list:
                    page.set.cookies({c['name']: c['value'] for c in cookies_list})
        except Exception:
            pass

    url = record.get("url", "").split("?")[0]
    method = record.get("method", "GET")
    req_headers = dict(record.get("request_headers", {})) if record.get("request_headers") else {}
    req_params = dict(record.get("request_params", {})) if record.get("request_params") else {}
    req_body = record.get("request_body")

    parsed_headers = _parse_json_override(override_headers)
    if parsed_headers:
        req_headers.update(parsed_headers)
    parsed_params = _parse_json_override(override_params)
    if parsed_params:
        req_params.update(parsed_params)
    if override_body:
        parsed_body = _parse_json_override(override_body)
        if parsed_body:
            req_body = parsed_body

    if method.upper() == "GET" and override_body:
        method = "POST"

    # Inject X-XSRF-TOKEN from XSRF-TOKEN cookie if available
    if tab_id and state._browser:
        try:
            tab_obj = state._browser.get_tab_by_id(tab_id)
            if tab_obj:
                xsrf_cookies = tab_obj.cookies(all_domains=False, all_info=False)
                xsrf = next((c["value"] for c in xsrf_cookies if c["name"] == "XSRF-TOKEN"), "")
                if xsrf:
                    req_headers["X-XSRF-TOKEN"] = xsrf
        except Exception:
            pass

    extra_headers = {}
    for k, v in req_headers.items():
        if k.lower() not in ("cookie", "content-length", "host"):
            extra_headers[k] = v

    t0 = time.perf_counter()
    try:
        if method.upper() == "GET":
            success = page.get(url, params=req_params, headers=extra_headers)
        elif method.upper() == "POST":
            if isinstance(req_body, dict):
                success = page.post(url, json=req_body, params=req_params, headers=extra_headers)
            elif isinstance(req_body, str):
                success = page.post(url, data=req_body, params=req_params, headers=extra_headers)
            else:
                success = page.post(url, params=req_params, headers=extra_headers)
        else:
            page.session.request(
                method.upper(), url, params=req_params,
                json=req_body if isinstance(req_body, dict) else None,
                data=req_body if isinstance(req_body, str) else None,
                headers=extra_headers,
            )
            success = page.response is not None
        elapsed_ms = (time.perf_counter() - t0) * 1000
    except Exception as e:
        return f"Request failed: {e}"

    tab_short = tab_id[:8] if tab_id else "?"
    resp = page.response
    status_code = resp.status_code if resp else 0
    lines = [f"[{tab_short}] {url}"]
    lines.append(f"Status: {status_code}  |  Time: {elapsed_ms:.0f}ms")
    lines.append("")
    lines.append("=== Request ===")
    lines.append(f"{method} {url}")
    if req_params:
        lines.append(f"Params: {json.dumps(req_params, ensure_ascii=False)}")
    if req_body:
        lines.append(f"Body: {json.dumps(req_body, ensure_ascii=False)}")
    lines.append("")
    lines.append("=== Response Headers ===")
    if resp:
        for k, v in dict(resp.headers).items():
            lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("=== Response Body (first 3000 chars) ===")
    if resp:
        try:
            body_text = resp.text
        except Exception:
            body_text = str(resp.content)
    else:
        body_text = "(no response)"
    if len(body_text) > 3000:
        body_text = body_text[:3000] + "\n... (truncated)"
    lines.append(body_text)
    return "\n".join(lines)


def _parse_json_override(raw: str) -> dict | None:
    if not raw or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
