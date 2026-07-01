# 013: 截图工具 — `scout_screenshot`（页面 + 元素）

> **来源**: ROADMAP.md 规划中 "截图工具" + "元素截图"
> **优先级**: P3（调试辅助，非核心）
> **影响范围**: `server.py` — 新增 `scout_screenshot` 工具

---

## 一、问题诊断

当前 web-scout 无截图能力。AI 在以下场景无法确认页面状态：

- 页面是否正确加载（登录墙、验证码、错误页）
- `scout_click`/`scout_action("scroll")` 后页面是否如预期变化
- 某个 DOM 容器是否正确选中

ROADMAP 原始描述：
> `tab.get_screenshot(path, name, full_page=True/False)` 一行实现整页/可视区截图。
> `ele.get_screenshot()` 对单个元素截图，可用于确认 DOM 容器是否正确。

---

## 二、DrissionPage 截图 API

| API | 参数 | 说明 |
|-----|------|------|
| `tab.get_screenshot(path, name, full_page)` | `path`: 目录；`name`: 文件名；`full_page`: 整页/可视区 | 返回文件路径 |
| `ele.get_screenshot(path, name, scroll_to_center)` | 同上 + `scroll_to_center`: 截图前滚动到视口中央 | 返回文件路径 |

---

## 三、目标设计

一个工具覆盖页面截图 + 元素截图：

```
scout_screenshot(name, full_page=True)        → 整页截图
scout_screenshot(name, full_page=False)       → 可视区截图
scout_screenshot(name, selector="css:...")    → 元素截图（selector 指定）
scout_screenshot(name, selector="#container") → 同上
scout_screenshot(name, uid=N)                 → 元素截图（scout_list_elements 的 uid）
```

---

## 四、实现细节

### 4.1 `server.py` — 新增 `scout_screenshot`

```python
@mcp.tool()
def scout_screenshot(
    name: str = "screenshot",
    full_page: bool = True,
    selector: str | None = None,
) -> str:
    """Take a screenshot of the current page or a specific DOM element.

    PAGE SCREENSHOT (omit selector):
        scout_screenshot(name="page1", full_page=True)   → full page
        scout_screenshot(name="viewport", full_page=False) → visible viewport

    ELEMENT SCREENSHOT (provide selector):
        scout_screenshot(name="result", selector="#results")
        scout_screenshot(name="card",  selector="div.card")

    Screenshots are saved to the current working directory as PNG files.
    Useful for debugging: verify page load state, check click results,
    confirm DOM container selection.

    Args:
        name: Base filename (without extension). Default "screenshot".
        full_page: True = entire page, False = visible viewport.
                   Ignored when selector is provided.
        selector: Optional CSS selector or element spec to screenshot.

    Returns:
        File path of the saved screenshot.
    """
    global _browser

    if not _browser:
        return "Error: call scout_open first."

    try:
        if selector:
            # 元素截图
            el = _browser.tab.ele(selector, timeout=3)
            if not el:
                # 尝试用 run_js 按 text 查找
                js = f"""
                var all = document.querySelectorAll('[class]');
                for (var i = 0; i < all.length; i++) {{
                    var el = all[i];
                    if ((el.textContent || '').includes('{selector}')) {{
                        el.scrollIntoView({{block: 'center'}});
                        return true;
                    }}
                }}
                return false;
                """
                found = _browser.tab.run_js(js)
                if found:
                    return f"Element with text '{selector}' found but not by CSS selector. Try scout_list_elements() to locate."
                return f"Element not found: '{selector}'."

            path = el.get_screenshot(name=f"{name}.png")
        else:
            path = _browser.tab.get_screenshot(
                name=f"{name}.png",
                full_page=full_page,
            )

        return f"Screenshot saved: {path}"

    except Exception as e:
        return f"Screenshot failed: {e}"
```

### 4.2 简化方案

实际上 ROADMAP 原文说"一行实现"。最简单有价值的形式：

```python
@mcp.tool()
def scout_screenshot(name: str = "screenshot", full_page: bool = True) -> str:
    """Take a screenshot of the current page.

    Args:
        name: Base filename (without extension). Default "screenshot".
        full_page: True = entire page, False = visible viewport.

    Returns:
        File path of the saved screenshot.
    """
    global _browser

    if not _browser:
        return "Error: call scout_open first."

    try:
        path = _browser.tab.get_screenshot(name=f"{name}.png", full_page=full_page)
        return f"Screenshot saved: {path}"
    except Exception as e:
        return f"Screenshot failed: {e}"
```

**采用简化方案**。元素截图不常用 — AI 更依赖 DOM 扫描输出而非截图。页面截图对调试确实有用，一行 API 即可。

---

## 五、测试要点

| 场景 | 调用 | 预期 |
|------|------|------|
| 整页截图 | `scout_screenshot("full")` | 保存 `full.png`，返回路径 |
| 可视区截图 | `scout_screenshot("view", full_page=False)` | 保存 `view.png` |
| 未调 scout_open | `scout_screenshot()` | `"Error: call scout_open first."` |
| 长页面 | B站首页 `scout_screenshot()` | 完整长截图 |

---

## 六、文件改动汇总

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/web_scout/server.py` | 新增 `scout_screenshot` 工具 | ~20 行 |
