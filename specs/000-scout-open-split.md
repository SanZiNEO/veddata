# 000: `scout_open` 拆分 — 文本优先 · 按需分析

> **来源**: ROADMAP.md 已知问题 #0
> **优先级**: P0（阻塞后续优化点 #6 / #7 / #8 的状态管理重构）
> **影响范围**: `server.py`（含 8 个工具函数） · `browser.py`

---

## 一、问题诊断

当前 `scout_open` 是一个"万能函数"，把六件事塞在一处：

```python
# server.py:61-129 (现状)
def scout_open(url, mode="auto"):
    1. 打开浏览器          # 必要
    2. 导航 + 提取文本     # 必要
    3. 检测登录墙          # 必要
    4. 启动 NetworkMonitor # 仅 api/dom 需要
    5. time.sleep(3)       # 所有 mode 都等 3 秒
    6. 创建 DOMScanner     # 仅 dom 需要
    7. 创建 Exporter       # 仅 export 需要
    8. 输出引导消息        # 误导 AI
```

**三个核心缺陷**:

| 缺陷 | 场景 | 损失 |
|------|------|------|
| `mode=text` 也等了 6 秒 | 纯文本页面（如停服公告） | 无意义等待 6s |
| API=0 时提示 `→ Next: scout_action('search', 'keyword')` | 富途停服公告 | 误导 AI 去做不可能成功的操作 |
| 全局变量 `_monitor`/`_dom` 只在 `scout_open` 内创建 | 任何页面 | 与 #8 状态丢失关联，耦合严重 |

---

## 二、目标设计

```
scout_open(url)
  └─ 打开浏览器 + 导航 + 等 DOM 稳定 + 提取 Markdown + 检测登录墙
  └─ 返回: 标题 + 全页文本
  └─ 不启动监听、不创建 DOMScanner、不输出引导消息

scout_analyze()
  └─ AI 读完文本后按需调用（无参数）
  └─ 启动 NetworkMonitor → 等 3 秒 → 捕获 API
  └─ 创建 DOMScanner → 扫描容器
  └─ 返回: API 数量 + DOM 容器数量
  └─ 失败场景: 已登录但 0 API → 不报错，正常返回 0
```

**去掉的内容**:
- `mode` 参数完全删除
- `"→ Next: ..."` 引导消息全部删除
- `_current_mode` 全局变量删除

**新增的错误处理**:
- `scout_list_apis` 在 `_monitor` 为 `None` 时: `"No APIs captured yet. Call scout_analyze() first."`（保持"未调用提示"清晰）
- `scout_list_elements` 在 `_dom` 为 `None` 时: `"No DOM data. Call scout_analyze() first."`

---

## 三、逐函数改动清单

### 3.1 `browser.py` — `BrowserSession`

**改动点**: `open()` 方法增加 DOM 稳定等待

```python
# browser.py:46-61 (现状)
def open(self, url: str) -> dict:
    self.tab.get(url)
    title = self.tab.title
    text = self.get_text()          # 可能在 DOM 未稳定时截取 ← ROADMAP #5
    ...
```

**修改为**:

```python
def open(self, url: str) -> dict:
    nav = self.tab.get(url)           # 导航（DrissionPage 内置等待 page_load）
    # 等待 DOM 关键元素出现（替代 time.sleep(2)）
    try:
        self.tab.wait.eles_loaded('a, button, input', timeout=5, any_one=True)
    except Exception:
        pass  # 哑页面没有交互元素是正常的
    title = self.tab.title
    text = self.get_text()
    ...
```

**DrissionPage API 参考**:
- `tab.get(url)` 已内置等待文档加载完成（`NavResult`），不需要额外 `sleep`
- `tab.wait.eles_loaded('a, button, input', timeout=5, any_one=True)` — 等待任意一个这类元素出现即返回，不阻塞固定时间
- 异常不要 raise — 纯公告类页面可能没有任何交互元素，这是正常情况

**不变的部分**:
- `get_text()` 逻辑不动（文本提取优化属于 #2）
- `close()` 不动
- `_detect_login()` 不动

- `_estimate_api_count()` 方法可以删除—不再使用

### 3.2 `server.py` — `scout_open`

**现状 (~48 行)**:

```python
@mcp.tool()
def scout_open(url: str, mode: str = "auto") -> str:
    global _browser, _monitor, _dom, _login, _exporter
    global _current_url, _current_mode, _login_pending

    # 登录检测
    if _login_pending and _browser:
        ...

    if not _browser:
        _browser = BrowserSession()
    _current_url = url
    _current_mode = mode

    result = _browser.open(url)

    # 登录墙分支
    _login = LoginDetector(_browser.tab)
    if _login.is_login_required():
        ...

    # 启动监听 + 等 3 秒 + 等 API
    _monitor = NetworkMonitor(_browser.tab)
    _monitor.start()
    time.sleep(3)
    api_count = _monitor.wait_new(timeout=3.0)

    # 创建 DOM + Exporter
    _dom = DOMScanner(_browser.tab)
    _exporter = Exporter()

    # 输出文本 + API 数 + 引导消息
    ...
```

**新实现（~30 行）**:

```python
@mcp.tool()
def scout_open(url: str) -> str:
    """Open a URL in Chromium, extract full page text as Markdown.

    Returns page title and full markdown text. No API monitoring or DOM
    scanning is performed — call scout_analyze() after reading the text if
    you need to inspect API endpoints or DOM containers.

    Args:
        url: Target website URL.

    Returns:
        Page title and full markdown text.
    """
    global _browser, _monitor, _dom, _login, _exporter, _login_pending

    # 如果有登录挂起，先检查是否已完成
    if _login_pending and _browser:
        login = LoginDetector(_browser.tab)
        if not login.is_login_required():
            _login_pending = False
        else:
            return ("登录未完成，请在浏览器中手动登录，然后调用 scout_wait_login()。\n"
                    "如果要换目标页面，先调用 scout_close() 关闭当前会话。")

    # 清理上一次的状态
    _monitor = None
    _dom = None
    _exporter = None

    if not _browser:
        _browser = BrowserSession()

    try:
        result = _browser.open(url)
    except Exception as e:
        return f"Failed to open page: {e}"

    # 检测登录墙
    _login = LoginDetector(_browser.tab)
    if _login.is_login_required():
        _login_pending = True
        title = _browser.tab.title or url
        text = _browser.get_text()
        return (f"页面已打开: {title}\n\n"
                f"=== 页面文本 ===\n{text}\n\n"
                f"⚠️ 此页面需要登录。登录后可获取完整 cookies 和更多 API 端点。\n"
                f"请在浏览器中手动登录，然后调用 scout_wait_login() 继续。")

    lines = [
        f"Page opened: {result['title'] or url}",
        "",
        "=== Page Text ===",
        result["text"],
    ]
    return "\n".join(lines)
```

**关键变化**:

| 项目 | 旧 | 新 |
|------|----|----|
| 参数 | `url, mode="auto"` | `url`（单参数） |
| 全局变量 | 创建 `_monitor`/`_dom`/`_exporter` | 全部初始化/重置 |
| 等待 | 固定 `time.sleep(3)` | 移到 `browser.open()` 内的 `wait.eles_loaded()` |
| 返回值 | 文本 + API 数 + `→ Next:` 提示 | 仅标题 + 文本 |
| `_current_url`/`_current_mode` | 设置 | 删除这两个变量 |

### 3.3 `server.py` — 新增 `scout_analyze`

**工具定义**:

```python
@mcp.tool()
def scout_analyze() -> str:
    """Analyze the current page: capture API endpoints and scan DOM containers.

    Call this AFTER reading the page text from scout_open(). This starts
    network monitoring, waits for API responses, and scans the DOM for
    repeated containers. The captured data is then available via
    scout_list_apis(), scout_list_elements(), scout_search(), etc.

    No parameters — always analyzes the currently open page.

    Returns:
        Count of APIs captured and DOM containers found.
    """
    global _monitor, _dom, _exporter, _browser

    if not _browser:
        return "Error: call scout_open first."

    if _login_pending:
        return "Error: call scout_wait_login() first."

    _monitor = NetworkMonitor(_browser.tab)
    _monitor.start()

    import time
    time.sleep(3)
    api_count = _monitor.wait_new(timeout=3.0)

    _dom = DOMScanner(_browser.tab)
    _exporter = Exporter()

    # 扫描 DOM 容器
    containers = _dom.find_containers()
    dom_count = len(_dom.containers_cache)

    lines = [
        f"Analyze complete: {api_count} APIs captured, {dom_count} DOM containers found.",
    ]
    if api_count > 0:
        lines.append("Use scout_list_apis() to list all captured endpoints.")
    if dom_count > 0:
        lines.append("Use scout_list_elements() to list interactive elements and containers.")

    return "\n".join(lines)
```

**说明**:
- 这里 `time.sleep(3)` 是合理的 — 需要等待页面 JS 发完初始 API 请求
- `_dom.find_containers()` 会被立即执行以填充 `containers_cache`，后续 `scout_list_elements()` 可以直接用
- 无参数 — 始终分析当前页面

### 3.4 `server.py` — 依赖工具的适配

以下工具当前检查 `if not _monitor:` / `if not _dom:` 时返回 `"Error: call scout_open first."`，需要更新错误信息:

| 工具 | 现状检查 | 新检查 |
|------|---------|--------|
| `scout_action` | `if not _browser` → "call scout_open first" | 不变 |
| `scout_wait_login` | `if not _browser or not _login` | 不变（登录检测不依赖 analyze） |
| `scout_list_apis` | `if not _monitor` → "call scout_open first" | `→ "No APIs captured. Call scout_analyze() first."` |
| `scout_inspect_api` | `if not _monitor` → "call scout_open first" | `→ "No APIs captured. Call scout_analyze() first."` |
| `scout_list_elements` | `if not _dom` → "call scout_open first" | `→ "No DOM data. Call scout_analyze() first."` |
| `scout_click` | `if not _dom` → "call scout_open first" | `→ "No DOM data. Call scout_analyze() first."` |
| `scout_search` | `if not _monitor or not _dom` | `→ "No data. Call scout_analyze() first."` |
| `scout_export` | `if not _monitor or not _exporter` | `→ "No data. Call scout_analyze() first."` |

**改动示例** (`scout_list_apis` 第 251-252 行):

```python
# 旧
if not _monitor:
    return "Error: call scout_open first."

# 新
if not _monitor:
    return "No APIs captured yet. Call scout_analyze() first after scout_open()."
```

### 3.5 `server.py` — 全局变量清理

删除:
```python
_current_url: str = ""       # 未在任何地方使用（仅赋值）
_current_mode: str = "auto"  # mode 参数删除后无用
```

保留:
```python
_browser: BrowserSession | None = None
_monitor: NetworkMonitor | None = None
_dom: DOMScanner | None = None
_login: LoginDetector | None = None
_exporter: Exporter | None = None
_login_pending: bool = False
```

### 3.6 `server.py` — MCP instructions 更新

`FastMCP` 的 `instructions` 参数（第 13-42 行）中删除了 MODES 和 EXPECTED WORKFLOW 的描述，更新为新流程:

```python
mcp = FastMCP("web-scout", instructions="""
Web Scout is a DATA SOURCE DISCOVERY tool, not a scraper or browser automation tool.

WHAT IT DOES:
- Opens web pages in a real browser → extracts text + captures API requests + scans DOM structure
- Outputs compressed field documentation for AI to write scrapers from
- Detects login walls and guides users through manual login

WHAT IT DOES NOT DO:
- Execute JavaScript, modify request headers, or manage cookies
- Scrape or download data — this is a reconnaissance tool
- Replace Chrome DevTools snapshot — DevTools shows detailed element trees for humans;
  Web Scout outputs compressed container summaries optimized for AI token consumption

EXPECTED WORKFLOW:
  1. scout_open(url) → read page text first
  2. AI reads text to decide if page is usable
  3. scout_analyze() → capture APIs + scan DOM (only when needed)
  4. scout_list_apis() → see captured endpoints
  5. scout_inspect_api(n) → view request params + response structure
  6. scout_export(n) → save raw JSON + field documentation

For DOM-heavy pages: scout_list_elements() → find containers → scout_inspect_dom()
For quick verification: scout_fetch_api(url, path) — open + capture + return in one call.
""")
```

### 3.7 `scout_wait_login` 适配

`scout_wait_login`（第 203-234 行）在登录成功后也会创建 `_monitor`/`_dom`/`_exporter`，并启动监听。新设计下，登录成功后应该只刷新文本，不自动做 analyze。

```python
# scout_wait_login: 登录成功后的行为
# 旧: 自动创建 monitor + 等 3 秒 + 返回 API 数 + 文本
# 新: 只刷新文本，AI 根据需要自行调用 scout_analyze()

def scout_wait_login(timeout: int = 300) -> str:
    global _login_pending, _browser, _login

    if not _browser or not _login:
        return "Error: call scout_open first."

    result = _login.wait_for_login(timeout)

    if result:
        _login_pending = False
        # 刷新页面文本（登录后 URL 可能变了）
        text = _browser.get_text()
        return (f"登录成功！\n\n"
                f"页面文本:\n{text[:2000]}\n\n"
                f"如果需要获取 API 端点，请调用 scout_analyze()。")
    else:
        return f"Login timeout ({timeout}s). Please try again."
```

### 3.8 `scout_fetch_api` — 不变

`scout_fetch_api` 是自包含工具，创建自己的 `BrowserSession` 和 `NetworkMonitor`，不受影响。

### 3.9 `scout_inspect_dom` — 不变

`scout_inspect_dom` 是自包含工具，不受影响。

### 3.10 `scout_action` — 不变

`scout_action` 中的 `search` 和 `scroll` 逻辑不变，仅错误消息适配（见 3.4）。

---

## 四、影响分析

### 向后兼容性

**不兼容。** `scout_open` 的 `mode` 参数被删除。旧调用方式:

```python
scout_open("url", mode="api")    # 旧 — 报错/unexpected keyword
scout_open("url", "auto")        # 旧 — 报错/too many args
scout_open("url")                # 新旧都支持
```

这是 MCP 工具级别变更，调用方是 AI（不是人类代码），AI 会自然适配新签名。

### 依赖的其它优化点

| 优化点 | 依赖关系 |
|--------|---------|
| #6 (Content-Type 过滤) | 无依赖 — 可独立进行 |
| #7 (SSR 内嵌 JSON) | 依赖 #0 — 需要在 analyze 阶段加提取逻辑 |
| #8 (Export 状态丢失) | 无直接依赖 — 全局变量仍在，但独立排查 FastMCP 进程模型 |
| #9 (滚动结果验证) | 无依赖 — 改动在 `scout_action` 内部 |

---

## 五、DrissionPage API 速查表

| 用途 | API | 文件 |
|------|-----|------|
| 导航到 URL | `tab.get(url)` 返回 `NavResult` | browser.py |
| 等待 DOM 元素出现 | `tab.wait.eles_loaded('a, button, input', timeout=5, any_one=True)` | browser.py |
| 获取页面 HTML | `tab.html` | browser.py |
| 获取页面标题 | `tab.title` | browser.py, server.py |
| 启动网络监听 | `tab.listen.start()` | monitor.py |
| 获取监听到的数据包 | `tab.listen.steps(timeout=..., gap=5)` | monitor.py |
| URL 检查 | `tab.url` | browser.py, login.py |

---

## 六、测试要点

1. **纯文本页面**（如公告页）: `scout_open` → 返回文本，无超时 → AI 读到停服公告直接结束
2. **SPA 页面**（如 B 站）: `scout_open` → 文本 → `scout_analyze` → API + DOM
3. **登录墙页面**: `scout_open` → 提示登录 → `scout_wait_login` → 文本 → `scout_analyze`
4. **未调 analyze 就调 list_apis**: 返回明确的 "Call scout_analyze() first" 提示
5. **`scout_fetch_api`**: 独立工具工作流不受影响
6. **`scout_inspect_dom`**: 独立工具工作流不受影响

---

## 七、文件改动汇总

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/web_scout/browser.py` | 修改 | `open()` 增加 `wait.eles_loaded()` 等待 DOM；删除 `_estimate_api_count()` |
| `src/web_scout/server.py` | 重写 | `scout_open` 简化；新增 `scout_analyze`；7 个工具错误消息适配；删除 `_current_url`/`_current_mode`；更新 MCP instructions |
| `src/web_scout/monitor.py` | 不变 | |
| `src/web_scout/dom.py` | 不变 | |
| `src/web_scout/export.py` | 不变 | |
| `src/web_scout/login.py` | 不变 | |
