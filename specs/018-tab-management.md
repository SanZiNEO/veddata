# 018: 标签页管理架构 — 单浏览器多 Tab

> **来源**: dxy.com 测试 — 浏览器反复断连 + AI 误用 fetch MCP
> **优先级**: P1（阻断实际使用）
> **影响范围**: `browser.py` 重写 + `server.py` 适配

---

## 一、现状问题

当前每次 `scout_open(url)` 都会销毁旧 Session，重新 `Chromium()` 创建新浏览器。dxy.com 实测：浏览器反复开关导致连接断开，AI 拿不到数据后转而调用其他 MCP。

```python
# 现状：每次打开新 URL 都重建浏览器
scout_open("url1") → new Chromium() on port 9222
scout_open("url2") → 关闭旧 Chromium() → new Chromium() on port 9222
# 反复几次后连接断开，tab → about:blank
```

**DrissionPage 已提供完整的 tab 管理**：

| API | 用途 |
|-----|------|
| `browser.new_tab(url)` | 创建新标签页并导航 |
| `tab.get(url)` | 在现有标签页导航 |
| `tab.activate()` | 将标签页切换到前台 |
| `tab.close()` | 关闭标签页 |
| `browser.latest_tab` | 获取最后激活的标签页 |
| `browser.get_tab(id)` | 按 ID 获取标签页 |
| `browser.tab_ids` | 所有标签页 ID 列表 |
| `browser.close_tabs(tabs)` | 批量关闭标签页 |

---

## 二、目标设计

```
Chromium 浏览器（唯一，端口 9222）
  ├── tab 1: https://www.bilibili.com/video/...
  ├── tab 2: https://www.xiaohongshu.com/explore/...
  ├── tab 3: https://www.zhihu.com
  └── tab 4: https://dxy.com/diseases

scout_open(url) → 如果已有 tab 是空页，复用；否则 new_tab(url)
scout_fetch()  → 操作当前活跃 tab
scout_action() → 操作当前活跃 tab
scout_close()  → 关闭当前 tab，保持浏览器存活
scout_analyze()→ 在指定 tab 上分析
```

---

## 三、`BrowserSession` 重写

### 3.1 新设计

```python
class BrowserSession:
    def __init__(self):
        self._browser: Chromium = None      # 全局唯一浏览器实例
        self._tabs: dict[str, ChromiumTab]  # tab_id → tab
        self._current_tab: str              # 当前活跃 tab_id
    
    def open(self, url: str) -> dict:
        """打开 URL，复用空 tab 或新建 tab"""
        if not self._browser:
            self._browser = Chromium(co)  # 只创建一次
            self._current_tab = None
        
        # 试着找一个空闲的空白 tab 复用
        for tid in self._browser.tab_ids:
            tab = self._browser.get_tab(tid)
            if tab.url in ('about:blank', '', 'chrome://newtab/'):
                tab.get(url)
                self._current_tab = tab.tab_id
                return self._extract_page_info(tab)
        
        # 没有空白 tab，新建
        tab = self._browser.new_tab(url)
        self._current_tab = tab.tab_id
        return self._extract_page_info(tab)
    
    def get_current_tab(self) -> ChromiumTab:
        """获取当前操作的 tab"""
        if self._current_tab:
            return self._browser.get_tab(self._current_tab)
        return self._browser.latest_tab
    
    def close_tab(self, tab_id: str = None):
        """关闭指定 tab 或当前 tab"""
        tid = tab_id or self._current_tab
        if tid:
            tab = self._browser.get_tab(tid)
            tab.close()
            # 切换到另一个 tab
            remaining = self._browser.tab_ids
            self._current_tab = remaining[0] if remaining else None
    
    def close(self):
        """关闭浏览器"""
        if self._browser:
            self._browser.quit()
```

### 3.2 旧方法保留

| 方法 | 改动 |
|------|------|
| `get_text()` | 不变 — 操作 `get_current_tab()` |
| `open()` | 重写 — 用 `new_tab()` 替代 `Chromium()` |

---

## 四、`server.py` 适配

### 4.1 `scout_open` 改动

```python
# 删除: 每次重建 BrowserSession
# 新增: BrowserSession 全局单例，open 方法复用空 tab 或新建

_browser = BrowserSession()  # 模块加载时创建

def scout_open(url: str) -> str:
    global _monitor, _dom, _exporter, _login_pending
    
    # 清理上一次的分析状态
    _monitor = None
    _dom = None
    _exporter = None
    
    result = _browser.open(url)     # ← 不再重建浏览器，走 tab 管理
    _login = LoginDetector(_browser.get_current_tab())
    ...
```

### 4.2 `scout_list_browsers` 改为 `scout_list_tabs`

```python
@mcp.tool()
def scout_list_tabs() -> str:
    """List all open tabs in the browser."""
    global _browser
    
    tabs = _browser._browser.get_tabs() if _browser._browser else []
    lines = [f"Open tabs ({len(tabs)}):"]
    for t in tabs:
        mark = " ← current" if t.tab_id == _browser._current_tab else ""
        lines.append(f"  [{t.tab_id[:8]}] {t.title[:60]}{mark}")
    return "\n".join(lines)
```

### 4.3 `scout_close` 改为关闭 Tab

```python
def scout_close():
    # 只关闭当前 tab，不关闭浏览器
    _browser.close_tab()
    return "Tab closed."
```

### 4.4 `scout_analyze` 创建 `NetworkMonitor` 时使用当前 tab

```python
# 改为从 BrowserSession 获取当前 tab
_monitor = NetworkMonitor(_browser.get_current_tab())
```

---

## 五、Tab 上下文返回规范

每个工具返回都带 `[Tab #N]` 标识，AI 随时知道在操作哪个标签页：

```
scout_open("bilibili.com")   → "[Tab #1] bilibili.com/video/..."
scout_open("zhihu.com")      → "[Tab #2] zhihu.com"
scout_fetch()                → "[Tab #2] Title: 首页 - 知乎 | URL: zhihu.com"
scout_action("scroll")       → "[Tab #2] Scrolled to bottom. 3 new APIs."
scout_analyze()              → "[Tab #2] Analyze complete: 15 APIs, 5 DOM, 0 SSR"
scout_list_tabs()            → "Open tabs (2):\n  [1] ← current | bilibili\n  [2] zhihu"
```

**`BrowserSession` 字段**：

| 字段 | 用途 |
|------|------|
| `_tabs: dict[str, dict]` | `tab_id → {num, url, title, page_title}` |
| `_next_tab_num: int` | 自增编号（1, 2, 3...） |
| `_current_tab: str` | 当前操作目标 tab_id |

**工具可接受 `tab` 参数切换上下文**：

```python
scout_fetch(tab=1)           # 切换到 Tab #1 并 fetch
scout_analyze(tab=3)         # 切换到 Tab #3 并分析
```

---

## 六、fetch 工具优先级

**问题**: AI 优先调用其他 MCP 的 `fetch`（HTTP 请求，无 JS 渲染），而不是 `scout_fetch`（浏览器渲染文本）。

**MCP instructions 增强**：

```
WHEN TO USE EACH FETCH:
- scout_fetch: For browser-rendered pages (SPA sites, JS-heavy pages).
  Shows what a real user sees, including content rendered after page load.
- Other fetch MCP: For raw HTML static pages only.
  Cannot render JavaScript or login-wall content.

PREFERENCE: Always try scout_fetch first. If the page is confirmed
to be static HTML (no JS required), you may use other fetch tools.
But for SPA sites (Vue/React), login walls, or dynamic content —
scout_fetch is the only option that works.
```

---

## 六、文件改动汇总

| 文件 | 改动 |
|------|------|
| `browser.py` | 重写 `BrowserSession`：单例 Chromium + tab 管理 |
| `server.py` | `scout_open` 不再重建浏览器；`scout_list_browsers` → `scout_list_tabs`；MCP instructions 增加 fetch 优先级 |
