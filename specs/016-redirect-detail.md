# 016: 重定向链 + 请求详情增强

> **来源**: ROADMAP.md 规划中 "请求详情增强" + "重定向链"（🔴 富途实测）
> **优先级**: P1（富途 quote-api → 302 → 403.html，当前不可见）
> **影响范围**: `monitor.py` — `filter_and_store()` + `get_api()`

---

## 一、问题诊断

### 1.1 重定向链不可见

富途实测场景：`quote-api` 返回 302 → 跳转到 `www.futunn.com/403`。当前 `scout_inspect_api` 只显示请求 URL，看不出发生了重定向。

**DrissionPage `DataPacket` 中已有的重定向信息**:

| 属性 | 值 | 当前是否存储 |
|------|-----|------------|
| `packet.url` | 请求 URL（原始） | ✅ `url` 字段 |
| `packet.response.url` | 响应 URL（跳转后） | ❌ |
| `packet.response.status` | 302/301 | ✅ |
| `packet.response.headers['Location']` | 跳转目标 | ❌ |
| `packet.response.headers` (全部) | 响应头 | ❌ |

### 1.2 响应头不完整

当前 `get_api()` 只输出请求头中的 6 个特定字段（Content-Type, Referer, Cookie, User-Agent, Origin, X-Requested-With）。自定义头（如富途 `quote-token`）完全不可见。

---

## 二、设计

### 2.1 `filter_and_store()` — 存储新字段

```python
# monitor.py — filter_and_store() 增加存储
existing["response_url"] = getattr(packet.response, 'url', url)
existing["response_headers"] = dict(resp_headers)
existing["redirect_status"] = status if status in (301, 302, 303, 307, 308) else None

# 新记录也包含这些字段
self.api_records.append({
    ...
    "response_url": getattr(packet.response, 'url', url),
    "response_headers": dict(resp_headers),
    "redirect_status": status if status in (301, 302, 303, 307, 308) else None,
})
```

### 2.2 `get_api()` — 展示重定向链 + 完整头

在 #011 的 `detail="full"` 模式下增强：

```python
# get_api() 中增加

# 重定向链（如果发生了重定向）
request_url = record.get("url", "")
response_url = record.get("response_url", "")
if response_url and response_url != request_url:
    status = record.get("response_status", "?")
    lines.append("")
    lines.append("=== Redirect ===")
    lines.append(f"Request:  {request_url}")
    lines.append(f"Status:   {status}")
    lines.append(f"Response: {response_url}")

    resp_headers = record.get("response_headers", {})
    location = resp_headers.get("Location", "")
    if location:
        lines.append(f"Location: {location}")

# 响应头（full 模式）
if detail == "full":
    resp_headers = record.get("response_headers", {})
    if resp_headers:
        lines.append("")
        lines.append("=== Response Headers ===")
        for k, v in resp_headers.items():
            if k.lower() == "set-cookie":
                v = _truncate_cookie(str(v)[:50])
            lines.append(f"  {k}: {v}")
```

### 2.3 完整输出示例（富途 redirect 场景）

```
=== Request ===
URL:    https://quote-api.futunn.com/...
Method: GET
...

=== Redirect ===
Request:  https://quote-api.futunn.com/...
Status:   302
Response: https://www.futunn.com/403
Location: https://www.futunn.com/403

=== Response Headers ===
  Content-Type: text/html
  Location: https://www.futunn.com/403
  Server: nginx
  ...

=== Response ===
Status: 302
Body: (empty — redirected)
```

---

## 三、文件改动汇总

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/web_scout/monitor.py` | `filter_and_store()` 新增 `response_url`、`response_headers`、`redirect_status` 三个字段；`get_api()` 增加 Redirect 段和 Response Headers 段 | ~30 行 |
