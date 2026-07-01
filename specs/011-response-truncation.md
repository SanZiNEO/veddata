# 011: 响应体截断选项 — preview / full 双模式

> **来源**: ROADMAP.md 已知问题 #11（🔴 B站实测）
> **优先级**: P1（AI 需要看完整字段结构才能写爬虫，当前截断令其无效）
> **影响范围**: `monitor.py` — `get_api()` · `export.py` — `compact()` · `server.py` — `scout_inspect_api`

---

## 一、问题诊断

**现状**: `monitor.py:31-35` 的 `_truncate_body()` 硬截断 2000 字符：

```python
def _truncate_body(body_str: str, max_len: int = 2000) -> str:
    if len(body_str) <= max_len:
        return body_str
    return body_str[:max_len] + "\n... (truncated)"
```

**B站实测**: `feed/rcmd` 响应体 607 个字段，`json.dumps` 后截断到 2000 字符。AI 看到的末尾是：

```json
"...(truncated)"
```

看不到完整的 `item` 数组结构和分页参数，无法据此写出爬虫代码。

**问题本质**: `scout_inspect_api` 的目标是让 AI "看懂这个 API 的结构和字段"，而不是"阅读完整的原始响应"。当前把所有角色混在一个输出里。

---

## 二、目标设计

`scout_inspect_api` 新增 `detail` 参数，两种模式：

```
scout_inspect_api(1)              → preview（默认）: 请求摘要 + 截断响应体
scout_inspect_api(1, "preview")   → 同上
scout_inspect_api(1, "full")      → full: 请求详情 + 完整字段结构（不截断原始响应体，输出压缩字段树）
```

### preview 模式（默认，保持现有行为）

- 请求方法、URL、关键 Header
- 响应状态码
- 响应体截断前 2000 字符
- 适用: AI 快速浏览多个 API，判断哪个有用

### full 模式

- 完整请求头（所有 header，不限于指定的 6 个）
- 完整请求参数 + Body
- **完整字段结构**（用压缩算法替代原始 JSON dump）
- 适用: AI 已确定这个 API 有价值，需要完整字段信息来写爬虫

---

## 三、实现细节

### 3.1 `monitor.py` — `get_api()` 增加 `detail` 参数

```python
def get_api(self, api_id: int, detail: str = "preview") -> str:
    """Return detailed request/response for a specific API endpoint.

    Args:
        api_id: Numeric ID of the API (1-based, from list_apis output).
        detail: "preview" (default) = truncated summary.
                "full" = complete headers + full field structure.

    Returns:
        Formatted text with request and response details.
    """
    record = None
    for rec in self.api_records:
        if rec["id"] == api_id:
            record = rec
            break
    for rec in self.embedded_records:
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
        # 完整字段结构：用压缩算法，不输出原始 JSON
        lines.append("Field structure:")
        lines.append(self._format_field_structure(resp_body))
    else:
        # 截断原始 JSON
        text = json.dumps(resp_body, indent=2, ensure_ascii=False)
        lines.append(f"Body (truncated):\n{_truncate_body(text)}")

    return "\n".join(lines)
```

### 3.2 `monitor.py` — 新增 `_format_field_structure()`

用压缩算法展开第一个数组项的全部字段（而非原始 JSON dump）：

```python
def _format_field_structure(self, obj, max_array_items: int = 3) -> str:
    """Format a JSON structure showing field names, types, and sample values.

    Compresses arrays to [item_count] + first item field list,
    compresses nested objects to their key list.
    """
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
```

### 3.3 `server.py` — `scout_inspect_api` 增加 `detail` 参数

```python
@mcp.tool()
def scout_inspect_api(index: int, detail: str = "preview") -> str:
    """Show full request and response details for a specific API.

    Args:
        index: API endpoint ID (from scout_list_apis output).
        detail: "preview" (default) = truncated summary with key headers.
                "full" = complete headers + full field structure tree.

    Returns:
        Formatted request/response details + compressed field document.
    """
    global _monitor, _exporter

    if not _monitor:
        return "No APIs captured. Call scout_analyze() first after scout_open()."

    record = _monitor.get_record(index)
    if not record:
        return _monitor.get_api(index, detail)

    inspect_text = _monitor.get_api(index, detail)

    if not _exporter:
        _exporter = Exporter()
    compact_text = _exporter.compact(record)

    parts = [inspect_text]
    if compact_text:
        parts.extend(["", "=== Field Document ===", compact_text])
    return "\n".join(parts)
```

### 3.4 `monitor.py` — `_truncate_body()` 保留

preview 模式仍使用截断，逻辑不变。`_truncate_body()` 函数保留不动。

---

## 四、full 模式输出示例（B站 feed/rcmd）

```
=== Request ===
URL:    https://api.bilibili.com/x/web-interface/wbi/index/top/feed/rcmd
Method: GET
Headers (all):
  Cookie: sessdata=abc123...def456
  User-Agent: Mozilla/5.0...
  Referer: https://www.bilibili.com/
  ...

=== Response ===
Status: 200
Field structure:
data: {object} — 3 keys
  data.item: [20] — first item fields:
    id: int = 12345678
    bvid: str = BV1xx411c7mD
    title: str = 某个视频标题...
    owner: {object} — 5 keys
      owner.mid: int = 12345
      owner.name: str = UP主名
      owner.face: str = https://i0.hdslb.com/...
    stat: {object} — 5 keys
      stat.view: int = 123456
      stat.danmaku: int = 1234
      stat.reply: int = 567
    ...
  data.has_more: bool = True
  data.page: int = 1
code: int = 0
message: str = success
```

---

## 五、与现有 `_exporter.compact()` 的关系

| 输出 | 作用 |
|------|------|
| `_format_field_structure()` | 全字段树 — 完整结构，压缩嵌套 |
| `_exporter.compact()` | 字段文档 — 提取关键字段 + 翻页参数 |

两者互补而非替代。`inspect_api` 返回两者都展示。

---

## 六、测试要点

| 场景 | 调用 | 预期 |
|------|------|------|
| 预览模式 | `scout_inspect_api(1)` | 截断 2000 字符，6 个关键 header |
| Full 模式 | `scout_inspect_api(1, "full")` | 字段结构树完整，无 `...(truncated)` |
| 大型响应 (>607 字段) | B站 feed/rcmd | full 模式完整字段结构 |
| 嵌入式 JSON | `scout_inspect_api(n)` | full 模式同样工作 |
| 空响应 | `scout_inspect_api(1, "full")` | 不报错，输出 "Field structure:" 为空 |

---

## 七、文件改动汇总

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/web_scout/monitor.py` | `get_api()` 增加 `detail` 参数；新增 `_format_field_structure()` 方法 | ~60 行 |
| `src/web_scout/server.py` | `scout_inspect_api` 增加 `detail` 参数，透传到 `get_api()` | ~5 行 |
