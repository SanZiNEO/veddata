# 008: Export 状态丢失 — 全局变量跨工具调用失效

> **来源**: ROADMAP.md 已知问题 #8（🔴 知乎实测）
> **优先级**: P0（阻断导出功能）
> **影响范围**: `server.py` — 全局变量管理

---

## 一、问题诊断

**现象**: `scout_open` 成功后调 `scout_export` 报 `"Error: call scout_open first."`。

```python
# server.py:49-53 — 全局变量
_browser: BrowserSession | None = None
_monitor: NetworkMonitor | None = None
_dom: DOMScanner | None = None
_login: LoginDetector | None = None
_exporter: Exporter | None = None
```

```python
# server.py:111 — scout_open 末尾
_exporter = Exporter()  # 赋值
```

```python
# server.py:370 — scout_export 入口检查
if not _monitor or not _exporter:
    return "Error: call scout_open first."  # ← 触发
```

**根因分析**:

| 根因 | 概率 | 说明 |
|------|------|------|
| 1. `_exporter` 未在 `scout_open` 中被赋值 | 低 | 代码明确有 `_exporter = Exporter()` |
| 2. 进入登录墙分支后早返回 | **高** | 当 `_login.is_login_required()` 为 True 时，`scout_open` 在 `_exporter = Exporter()` 这行之前 return，`_exporter` 保持 `None` |
| 3. FastMCP 进程模型导致全局变量重置 | 中 | FastMCP HTTP 模式 (`stateless_http=True`) 每次请求用新进程；stdio 模式共享进程但可能有其他机制 |
| 4. `_exporter` 被后续操作覆盖为 None | 低 | 只有 `scout_close` 和 `scout_open` 开头会重置 |

**已确认**: 根因 2 是主要问题。`scout_open` 的代码执行顺序是：

```
_browser.open(url)              # 第 88 行
_login = LoginDetector(...)     # 第 92 行
_login.is_login_required()      # 第 93 行 → True 时:
  → return "页面已打开..."      # 第 97-100 行 ← 早返回！_exporter 未创建！
_monitor = NetworkMonitor(...)  # 第 102 行 ← 未执行
...
_exporter = Exporter()          # 第 111 行 ← 未执行
```

但即便如此，登录墙场景期望走 `scout_wait_login` → 登录后 `_exporter` 才被创建。问题可能发生在：登录成功后网站重定向到非登录页（URL 变了），但此时 `_exporter` 仍然为 None。

---

## 二、修复设计

### 方案：延迟初始化 + 兜底重建

不依赖 `scout_open` 中 `_exporter` 的创建时机，改为**按需懒初始化**：

1. 每个需要 `_exporter` 的工具，在使用前检查是否为 None，为 None 则即时创建
2. `_monitor` 同理 — `scout_list_apis` 等工具中检查为 None 时返回友好提示（已在 #0 中改为 "call scout_analyze()"）

### 2.1 受影响工具 + 修复

| 工具 | 当前检查 | 修复 |
|------|---------|------|
| `scout_export` | `if not _monitor or not _exporter` → "call scout_open first" | `if not _monitor` → "call scout_analyze()"；`if not _exporter: _exporter = Exporter()` |
| `scout_inspect_api` | `if not _monitor` → "call scout_open first" | 不变（inspect 不需要 exporter，除非 compact 展示） |
| `scout_wait_login` | 创建 `_exporter = Exporter()` | **删除** — 登录成功后不再自动创建 exporter，由工具按需懒初始化 |

### 2.2 `scout_export` 修复

```python
@mcp.tool()
def scout_export(index: int, format: str = "both") -> str:
    global _monitor, _exporter, _browser

    if not _monitor:
        return "No data to export. Call scout_analyze() first after scout_open()."

    # 懒初始化 — 兜底重建
    if not _exporter:
        _exporter = Exporter()

    record = _monitor.get_record(index)
    if not record:
        return f"API #{index} not found."

    result = _exporter.export(record, format)

    if os.environ.get("AUTO_CLOSE", "true") == "true":
        try:
            _browser.close()
        except Exception:
            pass

    return result
```

### 2.3 `scout_inspect_api` 修复

```python
@mcp.tool()
def scout_inspect_api(index: int) -> str:
    global _monitor, _exporter

    if not _monitor:
        return "No APIs captured. Call scout_analyze() first after scout_open()."

    record = _monitor.get_record(index)
    if not record:
        return _monitor.get_api(index)

    inspect_text = _monitor.get_api(index)

    # 懒初始化 exporter（用于 compact 展示）
    if not _exporter:
        _exporter = Exporter()
    compact_text = _exporter.compact(record)

    parts = [inspect_text]
    if compact_text:
        parts.extend(["", "=== Field Document ===", compact_text])
    return "\n".join(parts)
```

### 2.4 `scout_wait_login` 简化

```python
def scout_wait_login(timeout: int = 300) -> str:
    global _login_pending, _browser, _login

    if not _browser or not _login:
        return "Error: call scout_open first."

    result = _login.wait_for_login(timeout)

    if result:
        _login_pending = False
        text = _browser.get_text()
        return (f"登录成功！\n\n"
                f"页面文本:\n{text[:2000]}\n\n"
                f"如果需要获取 API 端点，请调用 scout_analyze()。")
    else:
        return f"Login timeout ({timeout}s). Please try again."
```

**区别**: 不再创建 `_monitor`、`_dom`、`_exporter`。登录成功后 AI 自己调用 `scout_analyze()`。

---

## 三、全局变量生命周期

| 变量 | 创建时机 | 销毁时机 | 懒初始化 |
|------|---------|---------|---------|
| `_browser` | `scout_open` 首次调用 | `scout_close` | 否（需要端口池逻辑） |
| `_monitor` | `scout_analyze` | `scout_open` 重新打开新页面时清为 None | 否 |
| `_dom` | `scout_analyze` | 同上 | 否 |
| `_login` | `scout_open` | `_browser` 销毁时 | 否 |
| `_exporter` | **首次使用时懒创建** | 同上 | **是** |
| `_login_pending` | `scout_open` | `scout_wait_login` 成功 | N/A |

---

## 四、测试要点

| 场景 | 步骤 | 预期 |
|------|------|------|
| 正常流程 | `scout_open` → `scout_analyze` → `scout_export(1)` | 正常导出 |
| 无登录墙页面 | `scout_open` → `scout_analyze`（exporter 未创建）→ `scout_export(1)` | 懒创建 exporter，正常导出 |
| 登录墙页面 | `scout_open`（登录墙触发提前返回）→ `scout_wait_login` → `scout_analyze` → `scout_export(1)` | exporter 在 export 调用时懒创建，正常 |
| 多次 export | 同上流程 → `scout_export(1)` → `scout_export(2)` | 第二次不复建，复用已创建的 exporter |
| 跨页面切换 | `scout_open(A)` → `scout_analyze` → `scout_open(B)` → `scout_analyze` → `scout_export(1)` | 导出页面 B 的数据 |

---

## 五、文件改动汇总

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/web_scout/server.py` | `scout_export` 增加懒初始化 `_exporter`；`scout_inspect_api` 增加懒初始化 `_exporter`；`scout_wait_login` 删除 `_monitor`/`_dom`/`_exporter` 创建 | ~15 行 |
