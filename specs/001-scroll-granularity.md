# 001: 滚动操作粒度细化

> **来源**: ROADMAP.md 已知问题 #1
> **优先级**: P1（影响 AI 操作页面效率，但独立于 #0）
> **影响范围**: `server.py` — `scout_action("scroll", ...)` 分支

---

## 一、问题诊断

当前 `scout_action("scroll")` 只能触底：

```python
# server.py:189-198 (现状)
elif action == "scroll":
    try:
        _browser.tab.scroll.to_bottom()
        import time
        time.sleep(2)
        new_count = _monitor.wait_new(timeout=3.0) if _monitor else 0
        return f"Scrolled to bottom, captured {new_count} new APIs"
```

**缺陷**:

| 场景 | 问题 |
|------|------|
| AI 想回到顶部重新看布局 | 只能触底，无法回顶 |
| 无限滚动页面想翻一屏 | 触底会触发所有懒加载，太激进且耗时 |
| AI 想精确控制滚动距离 | 无法指定像素 |
| 长页面想分步滚动观察 | 必须一次性触底 |
| 回到顶部触发新数据（如 B 站下拉刷新变体） | 无法上滚 |

当前 DrissionPage 的 `tab.scroll` 提供了完整的方向和像素 API，`scout_action` 完全没有利用。

---

## 二、目标设计

扩展 `value` 参数，支持 6 种语义 + 精确像素：

```
scout_action("scroll")              → scroll to bottom（默认行为不变）
scout_action("scroll", "bottom")    → scroll to bottom（显式等价默认）
scout_action("scroll", "top")       → scroll to top
scout_action("scroll", "down")      → scroll down one viewport
scout_action("scroll", "up")        → scroll up one viewport
scout_action("scroll", "300")       → scroll down 300px（正数）
scout_action("scroll", "-200")      → scroll up 200px（负数）
```

---

## 三、实现细节

### 3.1 `server.py` — `scout_action` 的 scroll 分支重写

**现状 (~10 行)**:

```python
elif action == "scroll":
    try:
        _browser.tab.scroll.to_bottom()
        import time
        time.sleep(2)
        new_count = _monitor.wait_new(timeout=3.0) if _monitor else 0
        return f"Scrolled to bottom, captured {new_count} new APIs"
    except Exception as e:
        return f"Scroll failed: {e}"
```

**新实现**:

```python
elif action == "scroll":
    try:
        if value is None or value == "bottom":
            _browser.tab.scroll.to_bottom()
            desc = "bottom"
        elif value == "top":
            _browser.tab.scroll.to_top()
            desc = "top"
        elif value == "down":
            vp_height = _browser.tab.run_js("return window.innerHeight")
            _browser.tab.scroll.down(vp_height)
            desc = f"down {vp_height}px (1 viewport)"
        elif value == "up":
            vp_height = _browser.tab.run_js("return window.innerHeight")
            _browser.tab.scroll.up(vp_height)
            desc = f"up {vp_height}px (1 viewport)"
        elif value.lstrip("-").isdigit():
            px = int(value)
            if px >= 0:
                _browser.tab.scroll.down(px)
                desc = f"down {px}px"
            else:
                _browser.tab.scroll.up(abs(px))
                desc = f"up {abs(px)}px"
        else:
            return f"Unsupported scroll value: '{value}'. Use 'top', 'bottom', 'down', 'up', or pixel number."

        import time
        time.sleep(2)
        new_count = _monitor.wait_new(timeout=3.0) if _monitor else 0
        return f"Scrolled to {desc}, captured {new_count} new APIs"
    except Exception as e:
        return f"Scroll failed: {e}"
```

### 3.2 DrissionPage scroll API 速查

| 操作 | DP API | 说明 |
|------|--------|------|
| 触底 | `tab.scroll.to_bottom()` | 滚动到页面底部 |
| 回顶 | `tab.scroll.to_top()` | 滚动到页面顶部 |
| 下滚 N px | `tab.scroll.down(pixel)` | 向下滚动指定像素 |
| 上滚 N px | `tab.scroll.up(pixel)` | 向上滚动指定像素 |
| 获取视口高度 | `tab.run_js("return window.innerHeight")` | JS 获取当前视口高度 |

**为什么不使用 `tab.scroll.to_half()`、`tab.scroll.to_location()`、`tab.scroll.to_see()`？**

- `to_half()` 跳到页面 50% 位置，对无限滚动页面不准确
- `to_location(x, y)` 需要同时指定 x、y，AI 很难给出合理值
- `to_see(element)` 需要元素定位符，`scout_action` 的参数范式不适合

### 3.3 向后兼容性

**完全兼容。** 不传 `value` 时行为与旧版完全一致（默认触底）。旧调用：

```python
scout_action("scroll")                    # 旧 — 触底 → 新 — 触底 ✓
scout_action("scroll", "new_keyword")     # 旧 — 被 else 拦截 "unsupported" → 旧逻辑不变 ✓
```

---

## 四、测试要点

| 场景 | 调用 | 预期 |
|------|------|------|
| 默认触底 | `scout_action("scroll")` | 触底 + 返回 API 数 |
| 显式触底 | `scout_action("scroll", "bottom")` | 同上 |
| 回顶 | `scout_action("scroll", "top")` | 回到顶部 |
| 下翻一屏 | `scout_action("scroll", "down")` | 下滚 viewport 高度 |
| 上翻一屏 | `scout_action("scroll", "up")` | 上滚 viewport 高度 |
| 精确 500px | `scout_action("scroll", "500")` | 下滚 500px |
| 负值上滚 | `scout_action("scroll", "-300")` | 上滚 300px |
| 非数字非法值 | `scout_action("scroll", "abc")` | 返回 unsupported 提示 |
| 无 monitor | `scout_action("scroll")` | `_monitor` 为 None 时 new_count=0，正常返回 |

---

## 五、文件改动汇总

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/web_scout/server.py` | 修改 ~20 行 | `scout_action` 中 scroll 分支扩展，新增 docstring 更新 |

**docstring 更新**（改动 `scout_action` 函数注释）:

```python
def scout_action(action: str, value: str | None = None) -> str:
    """Execute an action on the page (search or scroll).

    Args:
        action: "search" or "scroll"
        value: Search keyword (required for "search").
               Scroll target (optional): "bottom", "top", "down", "up",
               or pixel number (e.g. "300" for down, "-200" for up).
               Default scroll is to bottom.

    Returns:
        Status message with count of new APIs captured.
    """
```
