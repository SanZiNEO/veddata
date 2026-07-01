# 014: DOM 扫描加速 — 批量字段提取 + 去重

> **来源**: ROADMAP.md 规划中 "DOM 扫描加速"
> **优先级**: P2（性能优化，非阻塞）
> **影响范围**: `dom.py` — `_extract_container_fields_tab()` + `find_containers()`

---

## 一、问题诊断

ROADMAP 原文：
> DrissionPage 的 `s_eles()` 先将 DOM 转为静态快照再查找，消除 CDP 往返开销。
> 使用时机: 当 `find_containers` 或 `inspect_container` 在 Python 侧循环调 `eles()` 且耗时 > 1s 时。

**实际瓶颈分析**: 当前代码已大量使用 `tab.run_js()` 做 JS 端批量提取，而非 Python 侧循环调 `eles()`。真正瓶颈在：

```python
# dom.py:178-199 — find_containers()
for rc in raw_candidates[:20]:
    tag = rc["tag"]
    cls = rc.get("cls") or rc.get("class", "")
    ...
    fields = self._extract_container_fields_tab(tag, cls)  # ← 每个候选一次 JS 调用！
```

`_extract_container_fields_tab()` 每次调 `tab.run_js()`（第 422 行）。20 个候选 = 20 次 CDP 往返，约 (20 × 30ms) = 600ms 纯粹网络等待。

### 另一个问题：重复 CSS 选择器扫描

`find_containers()` 返回的候选有时包含语义重复的选择器（如 `div.card`、`div.card.item`），虽然代码用 `seen_selectors` 去重（第 203-212 行），但扫描阶段仍然给所有候选都发了 JS 调用。

---

## 二、设计

### 2.1 改为单次 JS 调用批量提取所有候选容器的字段

合并 N 个独立 `tab.run_js()` 为 1 个 JS 调用：

```python
def _extract_all_container_fields(self, candidates: list[dict]) -> list:
    """Extract fields for all container candidates in a single JS call."""
    
    # 构建选择器数组
    selectors = json.dumps([f"{c['tag']}.{c.get('cls')}" for c in candidates])
    
    js = f"""
    var selectors = {selectors};
    var results = [];
    for (var s = 0; s < selectors.length; s++) {{
        var selector = selectors[s];
        try {{
            var els = document.querySelectorAll(selector);
            if (!els.length) {{ results.push([]); continue; }}
            var first = els[0];
            var leaves = first.querySelectorAll('[class]');
            var seen = {{}};
            var fields = [];
            for (var i = 0; i < leaves.length; i++) {{
                var leaf = leaves[i];
                var style = window.getComputedStyle(leaf);
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                var cls = leaf.getAttribute('class') || '';
                var parts = cls.split(/\\s+/);
                var name = 'field';
                var skip = {{'active':1, 'show':1, 'hide':1, 'selected':1, 'disabled':1, 'ng-binding':1}};
                for (var j = 0; j < parts.length; j++) {{
                    var c = parts[j];
                    if (!skip[c]) {{ name = c; break; }}
                }}
                if (name === 'field' || !name) continue;
                if (seen[name]) {{ seen[name]++; name = name + '_' + seen[name]; }}
                else {{ seen[name] = 1; }}
                var val = leaf.textContent || leaf.getAttribute('href') || leaf.getAttribute('src') || '';
                val = val.trim().substring(0, 46);
                if (!val) continue;
                var vtype = 'text';
                if (leaf.tagName === 'IMG') vtype = 'img';
                else if (leaf.tagName === 'A') vtype = 'href';
                fields.push({{name: name, type: vtype, sample: val}});
            }}
            results.push(fields);
        }} catch(e) {{
            results.push([]);
        }}
    }}
    return results;
    """
    try:
        return self.tab.run_js(js) or []
    except Exception:
        return [[] for _ in candidates]
```

### 2.2 修改 `find_containers()` 调用方式

```python
# 替换逐次调用为批量调用
all_fields = self._extract_all_container_fields(raw_candidates)

for i, rc in enumerate(raw_candidates[:20]):
    tag = rc["tag"]
    cls = rc.get("cls") or rc.get("class", "")
    if not cls:
        continue
    
    fields = all_fields[i] if i < len(all_fields) else []  # 从批量结果取
    if not fields:
        continue
    
    # 后续评分和排序逻辑不变...
```

### 2.3 删除旧的 `_extract_container_fields_tab()`

被 `_extract_all_container_fields()` 替代后，删除这个方法。但检查 `inspect_container()` 是否单独调用它 — 否，`inspect_container()` 只读缓存。

---

## 三、效果预估

| 场景 | 当前 | 优化后 |
|------|------|--------|
| 20 个候选 | 20 × ~30ms JS 往返 = ~600ms | 1 × ~50ms JS 往返 = ~50ms |
| B站首页 | ~800ms DOM 扫描 | ~100ms |
| 豆瓣话题广场 | ~600ms | ~60ms |

---

## 四、测试要点

| 场景 | URL | 验证 |
|------|-----|------|
| 正常 SPA | B站/知乎 | `find_containers()` 返回字段与优化前一致 |
| 无候选容器 | 纯文本页面 | 返回 `"No repeated containers found."` |
| 单候选 | 简单页面 | 返回 1 个容器，字段正常 |
| JS 异常 | 任意 | 静默返回空列表，不崩溃 |

---

## 五、文件改动汇总

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/web_scout/dom.py` | 新增 `_extract_all_container_fields()`；修改 `find_containers()` 调用方式；删除 `_extract_container_fields_tab()` | ~60 行 |
