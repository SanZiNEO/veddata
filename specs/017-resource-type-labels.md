# 017: 资源类型标注 — `list_apis` 输出 `[Script]`/`[SSE]` 标签

> **来源**: ROADMAP.md 规划中 "资源类型标注"（🟡 低优）
> **优先级**: P3（锦上添花，非阻塞）
> **影响范围**: `monitor.py` — `list_apis()` + `filter_and_store()`

---

## 一、问题诊断

当前 `list_apis` 输出同质化：

```
[1] GET /api/feed/rcmd  1 time → 607 fields
[2] GET /api/search    3 times → 45 fields
```

AI 看不到请求类型差异。JSONP `[Script]` 和标准 `[XHR]` 在同一列表里难以区分。

---

## 二、设计

`filter_and_store()` 已记录 `resourceType`（#010 引入）。利用这个字段在 `list_apis` 中加标签。

### 2.1 标签映射

| resourceType | 标签 | 说明 |
|-------------|------|------|
| `XHR` | （无） | 默认 API，最常见的 |
| `Fetch` | （无） | 默认 API |
| `Script` | `[JSONP]` | `<script>` 插入的 JSONP 请求 |
| `EventSource` | `[SSE]` | 服务端推送 |
| `Document` | `[SSR]` | 内嵌 JSON（#7） |

### 2.2 `list_apis()` 修改

```python
def list_apis(self, keyword: str | None = None) -> str:
    all_records = self.api_records + self.embedded_records
    ...
    
    lines = []
    for rec in all_records:
        method = rec["method"]
        path = rec["path"]
        count = rec["count"]
        fields = rec["field_count"]
        
        # 资源类型标签
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
```

### 2.3 输出示例

```
[1] GET /api/feed/rcmd  1 time → 607 fields
[2] [JSONP] GET /rankhandler.aspx  3 times → 120 fields
[3] [SSR] window.__INITIAL_STATE__  1 time → 350 fields
[4] [SSE] GET /live/stream  1 time → 12 fields
```

---

## 三、`filter_and_store()` 微调

需要在存储时保存 `resource_type`：

```python
# filter_and_store() 中，现有记录和新记录都加
existing["resource_type"] = getattr(packet, 'resourceType', 'XHR')
```

---

## 四、文件改动汇总

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/web_scout/monitor.py` | `filter_and_store()` 存储 `resource_type`；`list_apis()` 增加标签逻辑 | ~15 行 |
