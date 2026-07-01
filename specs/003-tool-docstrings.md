# 003: 工具 docstring 补全 — 使用场景示例化

> **来源**: ROADMAP.md 已知问题 #3
> **优先级**: P2（不影响功能，但影响 AI 使用效果）
> **影响范围**: `server.py` — 3 个工具的 docstring

---

## 一、问题诊断

ROADMAP 列出了三个工具的 docstring 缺陷：

| 工具 | 现状问题 |
|------|---------|
| `scout_action("scroll")` | docstring 没写清楚可用于无限滚动加载，AI 不知道滚动能触发新 API |
| `scout_click` | 不知道可以点翻页按钮触发新 API |
| `scout_list_browsers` | 新加的工具，AI 不知道它的存在和用途 |

docstring 是 MCP 工具提供给 AI 的唯一说明。写得不够"AI 友好"= AI 不会用。

---

## 二、逐工具 docstring 重写

### 2.1 `scout_action` — 滚动 + 搜索完整场景

**现状**:

```python
def scout_action(action: str, value: str | None = None) -> str:
    """Execute an action on the page (search or scroll).

    Args:
        action: "search" or "scroll"
        value: Search keyword (required for "search")

    Returns:
        Status message with count of new APIs captured.
    """
```

**问题**:
- `scroll` 没说可以做无限滚动翻页加载更多 API
- `search` 没说可以在搜索框输入并提交
- 没有典型工作流示例

**新版**:

```python
def scout_action(action: str, value: str | None = None) -> str:
    """Execute an action on the page: search or scroll.

    SEARCH:
      Finds a visible search input field, types the keyword, and presses Enter.
      Useful for triggering search-related API requests on SPA sites.

    SCROLL:
      Scrolls the page to load more content or reveal new elements.
      Supports these values:
        - omitted / "bottom" : scroll to page bottom (trigger lazy-load APIs)
        - "top"               : scroll to page top
        - "down"              : scroll down one viewport height
        - "up"                : scroll up one viewport height
        - "300"               : scroll down exactly 300px
        - "-200"              : scroll up exactly 200px

    After executing, returns the number of newly captured API endpoints.
    This is how you trigger infinite-scroll pagination or dynamic content
    loading — scroll, then check scout_list_apis() for new endpoints.

    Args:
        action: "search" or "scroll"
        value:   For "search": the keyword to type into the search box.
                 For "scroll": scroll target (see options above). Defaults to bottom.

    Returns:
        Status message with count of new APIs captured after the action.
    """
```

---

### 2.2 `scout_click` — 点击翻页

**现状**:

```python
def scout_click(index: int) -> str:
    """Click a page element by its index.

    Args:
        index: Element ID from scout_list_elements output.

    Returns:
        Status message with count of new APIs triggered.
    """
```

**问题**:
- 没说点击"下一页"按钮可以触发翻页 API
- 没说 `scout_list_elements` → `scout_click(index)` 的工作流

**新版**:

```python
def scout_click(index: int) -> str:
    """Click a page element by its ID from scout_list_elements().

    Typical workflow:
      1. scout_list_elements() → see interactive elements with IDs
      2. scout_click(n)           → click the n-th element
      3. scout_list_apis()        → see new API endpoints triggered by the click

    Common use cases:
      - Click "next page" buttons to capture pagination API calls
      - Click tabs/filters to load different data endpoints
      - Click category links to explore different API responses

    After clicking, waits 2 seconds and returns how many new APIs were captured.

    Args:
        index: Element ID from scout_list_elements output.

    Returns:
        Status message with element clicked and count of new APIs triggered.
    """
```

---

### 2.3 `scout_list_browsers` — 多浏览器管理

**现状**:

```python
def scout_list_browsers() -> str:
    """List all running browser instances on ports 9222-9231.

    Shows which ports have active browsers. AI can then decide
    which ones to keep and call scout_close to clean up the rest.
    """
```

**问题**:
- 没说"为什么有这个工具"——多浏览器场景的用途
- 没说典型使用方式

**新版**:

```python
def scout_list_browsers() -> str:
    """List all running browser instances across ports 9222-9231.

    Shows each port's status: active browser (with page title + URL) or free.
    Useful for managing multiple concurrent browsing sessions and cleaning up
    stale browser processes from previous runs.

    Typical usage:
      - Call this if scout_open() fails with port conflicts
      - Call this when you suspect leftover browser processes are wasting resources
      - After listing, call scout_close() to release free ports if needed
      - This tool reads port status passively — it does not affect running sessions

    Returns:
        Per-port status list with page info for active instances.
    """
```

---

## 三、docstring 编写原则

1. **场景先行** — 先说"什么时候用这个工具"，再说参数
2. **工作流示例** — 用 `1. → 2. → 3.` 格式列出典型调用链
3. **不说"how it works"** — AI 不需要知道内部实现，只要知道"调用它会发生什么"
4. **关键动词明确** — `trigger`、`capture`、`list`、`click` 比 `execute`、`perform` 精准

---

## 四、文件改动汇总

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/web_scout/server.py` | 重写 3 个 docstring | `scout_action`、`scout_click`、`scout_list_browsers` |
