# 004: 批量导出 `scout_export_all`

> **来源**: ROADMAP.md 已知问题 #4
> **优先级**: P1（提升 AI 效率，独立于 #0）
> **影响范围**: `server.py` — 新增工具函数 · `export.py` — 无需改动

---

## 一、问题诊断

当前 `scout_export` 一次只能导出一个 API：

```python
# server.py:357-385 (现状)
def scout_export(index: int, format: str = "both") -> str:
    record = _monitor.get_record(index)
    if not record:
        return f"API #{index} not found."
    result = _exporter.export(record, format)
    ...
    return result
```

**场景伤害**：AI 探索完一个页面，捕获了 5 个 API 端点，想全部导出保存。需要调 5 次 `scout_export` + 等待 5 次返回 → 大量往返。

ROADMAP 第 77 行描述的场景完全一致：
> `scout_export` 一次只能导一个 API。探索 5 个数据源需要调 5 次导出 + 5 次 inspect。

---

## 二、目标设计

新增 `scout_export_all`，遍历所有已捕获 API，一次性批量导出：

```
scout_export_all()                  → 导出全部，默认 format="both"
scout_export_all("raw")             → 只导出原始 JSON
scout_export_all("compact")         → 只导出字段文档
scout_export_all("both")            → 两者都导出
```

返回摘要信息：导出多少条、保存在哪个目录。

---

## 三、实现细节

### 3.1 `server.py` — 新增 `scout_export_all`

```python
@mcp.tool()
def scout_export_all(format: str = "both") -> str:
    """Export all captured API data sources at once.

    Iterates through every captured API endpoint and exports each one
    to the response/ directory. Much faster than calling scout_export()
    multiple times when you have many endpoints.

    Args:
        format: "raw" | "compact" | "both" (default "both").
            - "raw": save raw JSON response body to file
            - "compact": generate compressed field documentation
            - "both": do both

    Returns:
        Summary of how many APIs were exported and the output directory.
    """
    global _monitor, _exporter

    if not _monitor or not _exporter:
        return "No data to export. Call scout_analyze() first after scout_open()."

    records = _monitor.api_records
    if not records:
        return "No APIs captured yet."

    results = []
    for record in records:
        try:
            part = _exporter.export(record, format)
            path = record["path"]
            results.append(f"  [{record['id']}] {record['method']} {path}  → exported")
        except Exception as e:
            results.append(f"  [{record['id']}] {record['method']} {record['path']}  → FAILED: {e}")

    lines = [
        f"Batch export complete: {len(results)} APIs exported.",
        f"Output directory: {_exporter.response_dir}/",
        "",
    ]
    lines.extend(results)
    return "\n".join(lines)
```

### 3.2 `export.py` — 无需改动

`Exporter.export()` 已经接受单个 `api_record` 并独立工作。`scout_export_all` 只是在一个循环里调用它。`save_raw()` 的文件去重逻辑（`_page2` 后缀）是幂等的，重复调用没事。

### 3.3 与 `scout_export` 的关系

| 工具 | 用途 |
|------|------|
| `scout_export(n)` | 精确定位 — 只导第 n 个 API，深入查看 |
| `scout_export_all()` | 全量导出 — 所有 API 一次性带走 |

两个工具互补，不替代。`scout_export` 仍然保留给单 API 深入场景。

### 3.4 是否为每个 API 输出字段文档

当 `format="compact"` 或 `"both"` 时，每个 API 都会生成字段文档。这意味着 `scout_export_all("both")` 的输出可能很长（5 个 API × 各自的字段文档），返回给 AI 的文本会比较冗长。

**策略**：`export_all` 返回的摘要里只列文件名和路径，不内联字段文档。AI 需要深入某个 API 时用 `scout_export(n)` 单独导出。

修改 `Exporter.export()` 调用方式 — 传 `compact` 时仍然保存文件，但 `scout_export_all` 不在返回结果中展示完整文档：

```python
# scout_export_all 内部 — 不收集 compact 文本到返回值
for record in records:
    try:
        if format in ("raw", "both"):
            path = _exporter.save_raw(record)
            results.append(f"  [{record['id']}] raw JSON → {path}")
        if format in ("compact", "both"):
            path = _exporter.save_compact_doc(record)  # 需要新增这个方法
            results.append(f"  [{record['id']}] field doc → {path}")
    except Exception as e:
        results.append(f"  [{record['id']}] FAILED: {e}")
```

这需要 `Exporter` 新增一个 `save_compact_doc()` 方法，把 `compact()` 的结果写入文件而不是返回字符串。

### 3.5 `export.py` — 新增 `save_compact_doc()`

```python
def save_compact_doc(self, api_record: dict) -> str:
    """Save compact field documentation to a .md file.

    Returns:
        File path of the saved document.
    """
    doc_text = self.compact(api_record)
    url = api_record["url"]
    api_path = url.split("?")[0]
    parts = [p for p in api_path.rstrip("/").split("/") if p]
    if len(parts) >= 2:
        filename = f"{parts[-2]}_{parts[-1]}_fields.md"
    elif parts:
        filename = f"{parts[-1]}_fields.md"
    else:
        filename = "api_fields.md"

    filepath = os.path.join(self.response_dir, filename)
    os.makedirs(self.response_dir, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(doc_text)
    return filepath
```

---

## 四、测试要点

| 场景 | 调用 | 预期 |
|------|------|------|
| 5 个 API 全部导出 | `scout_export_all()` | 5 个文件写入 `response/`，返回摘要 |
| 0 个 API | `scout_export_all()` | 返回 "No APIs captured yet." |
| 未调 analyze | `scout_export_all()` | 返回 "No data to export. Call scout_analyze() first." |
| format=raw | `scout_export_all("raw")` | 只生成 JSON 文件，不生成 .md |
| 文件重名 | 两次导出同一页面 | 自动追加 `_page2` 后缀（save_raw 已有此逻辑） |
| compact 文件保存 | `scout_export_all("compact")` | 生成 `*_fields.md` 文件 |

---

## 五、文件改动汇总

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/web_scout/server.py` | 新增 `scout_export_all` 工具函数 (~40 行) | |
| `src/web_scout/export.py` | 新增 `save_compact_doc()` 方法 (~20 行) | |
