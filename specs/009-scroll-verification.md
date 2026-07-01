# 009: 滚动结果验证 — 反馈 API + DOM 变化

> **来源**: ROADMAP.md 已知问题 #9
> **优先级**: P2（提升 AI 操作信心，独立于 #0）
> **影响范围**: `server.py` — `scout_action("scroll", ...)` 分支

---

## 一、问题诊断

当前 `scout_action("scroll")` 返回值太简略：

```python
# server.py:189-198 (现状)
elif action == "scroll":
    ...
    new_count = _monitor.wait_new(timeout=3.0) if _monitor else 0
    return f"Scrolled to bottom, captured {new_count} new APIs"
```

**AI 决策困境**:

| 场景 | 当前返回 | AI 不知道 |
|------|---------|----------|
| 滚动后没有新 API | `"captured 0 new APIs"` | 是否已到底？是否滚动失效？ |
| 滚动后出现新 DOM 容器 | （不报告） | 是否有新内容可见？ |
| 无限滚动加载了 3 页 | `"captured 3 new APIs"` | 哪个 API 是翻页的？ |

---

## 二、目标设计

### 增强返回值

```
滚动前: 记录 _monitor API 总数 + _dom 容器数
滚动 + 等待 2s + 捕获 API + 等 3s
滚动后: 统计新增 API + 新增/变化的 DOM 容器
```

**返回格式**:

```
Scrolled to bottom, 3 new APIs captured. (total: 8 APIs)
DOM containers: 5 total, 2 new since last scan.
```

### 与 #1 的联动

`#1` 扩展了 scroll 的 `value` 参数。本条在 `#1` 改动基础上叠加返回值增强：

```python
# 结合 #1 + #9 的最终结果
scout_action("scroll", "down")  → "Scrolled to down 800px (1 viewport), 2 new APIs. DOM: 4 total."
scout_action("scroll")           → "Scrolled to bottom, 0 new APIs (already at end?). DOM: 3 total."
```

---

## 三、实现细节

### 3.1 `server.py` — scroll 分支增强

```python
elif action == "scroll":
    try:
        # 滚动前快照
        api_before = len(_monitor.api_records) if _monitor else 0
        dom_before = len(_dom.containers_cache) if _dom else 0

        # === 滚动逻辑（来自 #1 设计） ===
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

        # === 滚动后统计（#9 新增） ===
        new_apis = 0
        if _monitor:
            new_apis = _monitor.wait_new(timeout=3.0)

        dom_new = 0
        dom_total = 0
        if _dom:
            _dom.find_containers()  # 重新扫描
            dom_total = len(_dom.containers_cache)
            dom_new = max(0, dom_total - dom_before)

        # === 构建返回值 ===
        parts = [f"Scrolled to {desc}."]

        if _monitor:
            if new_apis > 0:
                parts.append(f"{new_apis} new APIs captured (total: {len(_monitor.api_records)}).")
            else:
                parts.append(f"0 new APIs. Total: {len(_monitor.api_records)}.")

        if _dom:
            if dom_new > 0:
                parts.append(f"DOM: {dom_total} containers, {dom_new} new since last scan.")
            else:
                parts.append(f"DOM: {dom_total} containers (no new).")

        return " ".join(parts)

    except Exception as e:
        return f"Scroll failed: {e}"
```

### 3.2 `dom.py` — `find_containers()` 多次调用安全

`DOMScanner.find_containers()` 每次调用都会：
1. `self.containers_cache.clear()`
2. `self._next_cont_id = 1`

这意味着第二次调用会**完全替换**容器缓存。对于滚动后的 DOM 扫描，这是预期行为 — 新扫描结果反映当前页面状态。

但 `dom_before > dom_total` 可能导致 `dom_new < 0`。已在代码中用 `max(0, dom_total - dom_before)` 防御。

### 3.3 `api_before` 可用但非必要

`api_before` 记录了滚动前的 API 总数（不是用于 `dom_new` 那类 diff，而是给返回值补充上下文）。当前主要依赖 `wait_new()` 返回的新增数量。

---

## 四、测试要点

| 场景 | 调用 | 预期返回 |
|------|------|---------|
| 无限滚动有新 API | `scout_action("scroll")` | `"Scrolled to bottom. 3 new APIs captured (total: 5). DOM: ..."` |
| 已到底，无新 API | 同上 | `"Scrolled to bottom. 0 new APIs. Total: 5. DOM: ..."` |
| 上升，scroll=up | `scout_action("scroll", "up")` | `"Scrolled to up 800px (1 viewport). ..."` |
| 无 DOM 数据 | scroll 后 inspect | DOM 部分显示 "no new" 或省略 |
| 无 _monitor | 未调 analyze 就 scroll | `new_apis = 0`，文本正常返回 |
| 精确像素 | `scout_action("scroll", "500")` | `"Scrolled to down 500px. ..."` |

---

## 五、文件改动汇总

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/web_scout/server.py` | `scout_action` 中 scroll 分支：增加滚动前快照 + 滚动后 DOM 重扫描 + 增强返回值 | ~20 行新增 |
