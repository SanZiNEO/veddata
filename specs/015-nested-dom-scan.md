# 015: 嵌套 DOM 扫描 + 静态快照加速

> **来源**: ROADMAP.md 规划中 "DOM 扫描加速" + "嵌套 DOM 扫描"
> **优先级**: P1（用户确认优先做）
> **影响范围**: `dom.py` — 全面重写扫描策略

---

## 一、问题诊断

### 1.1 当前扫描丢失嵌套层级

```python
# dom.py:382-426 — _extract_container_fields_tab()
# 只提取第一层 [class] 叶子节点，看不到嵌套结构
```

| 页面结构 | 当前输出 | 丢失信息 |
|---------|---------|---------|
| `<table>` → `<tr>` → `<td>` | `td.cell` 平铺 | `colspan`/`rowspan` 合并单元格关系 |
| `<ul>` → `<li>` → `<ul>` → `<li>` | `li.item` 平铺 | 二级列表嵌套关系 |
| `<div.card>` → `<div.header>` + `<div.body>` | `div.header`, `div.body` 平铺 | header 和 body 是 card 的子区域 |

### 1.2 当前扫描慢

`#014` 已解决：批量 JS 调用替代逐容器单独调用。但仍有 DrissionPage 内置的 `s_eles()` 静态快照方案可用，官方文档实测 **14x** 加速（4s → 0.28s）。

---

## 二、目标设计

### 2.1 三层策略优先级

```
策略 1（最优先）: s_eles() 静态快照 → 在 Python 侧遍历静态 DOM 树
    ├── 快（14x），无 CDP 往返
    ├── 丢失: JS 渲染的动态文本、hover/focus 伪类
    └── 适用: 页面已完成服务端渲染，DOM 稳定

策略 2（中等优先）: 批量 tab.run_js() → 单次 JS 调用拿全量数据
    ├── 中等，1 次 CDP 往返
    ├── 保留动态内容
    └── 适用: SPA 页面，静态快照拿不到 JS 渲染内容

策略 3（兜底）: 逐次 tab.run_js() — 当前方案
    ├── 慢，每容器一次 CDP
    └── 适用: 前两种都失败时
```

### 2.2 嵌套扫描输出格式

```
[1] div.card[] 共 20 条 → title, author, time
  ├── div.card-header[]      (嵌套容器)
  │   ├── title: text = "标题"
  │   └── span.tag: text = "标签"
  ├── div.card-body[]
  │   └── desc: text = "描述文本..."
  └── div.card-footer[]
      ├── author: text = "作者名"
      └── time: text = "2024-01-15"

[2] table.result[] 共 50 条 → 产品, 价格, 库存
  ├── thead > tr > ...
  └── tbody > tr[] (50 rows)
      ├── td[0]: text = "产品A"
      ├── td[1]: text = "¥99"
      └── td[2]: text = "有货"
```

---

## 三、实现设计

### 3.1 `DOMScanner` 新增 `_get_static_body()`

```python
def _get_static_body(self):
    """Convert body to static snapshot for fast DOM traversal.
    
    Returns:
        Static element of <body>, or None if page has no body / error.
    """
    try:
        body = self.tab.ele('tag:body', timeout=2)
        if body:
            return body.s_ele()
    except Exception:
        pass
    return None
```

### 3.2 重写 `find_containers()` — 策略1（静态快照）

```python
def find_containers(self) -> str:
    self.containers_cache.clear()
    self._next_cont_id = 1

    # 策略 1: 尝试静态快照
    static_body = self._get_static_body()
    if static_body:
        return self._find_containers_static(static_body)

    # 策略 2: 降级到批量 JS
    return self._find_containers_js_batch()
```

### 3.3 静态快照下的容器发现（策略 1）

```python
def _find_containers_static(self, static_body) -> str:
    """Use s_eles() on static snapshot to find containers, then walk nested trees."""
    
    # 用 s_eles() 获取所有带 class 的静态元素
    all_elements = static_body.s_eles('[class]')
    if not all_elements:
        return "No repeated containers found."

    # 统计父元素下的重复子元素模式（原 find_containers 的 JS 逻辑，改为 Python 侧）
    parent_map: dict[str, dict[str, int]] = {}
    for el in all_elements:
        try:
            p = el.parent()
            if not p:
                continue
            ptag = p.tag
            pcls = (p.attr('class') or '').split()[0] if p.attr('class') else ''
            pkey = f"{ptag}.{pcls}"
            if not pkey or pkey == '.':
                continue
            ctag = el.tag
            ccls = (el.attr('class') or '').split()[0] if el.attr('class') else ''
            if not ccls:
                continue
            ckey = f"{ctag}.{ccls}"
            if pkey not in parent_map:
                parent_map[pkey] = {}
            parent_map[pkey][ckey] = parent_map[pkey].get(ckey, 0) + 1
        except Exception:
            continue

    # 筛选重复 ≥3 的候选项（保持不变）
    candidates = []
    for pkey, cmap in parent_map.items():
        for ckey, cnt in cmap.items():
            if cnt < 3:
                continue
            cparts = ckey.split('.')
            candidates.append({
                'tag': cparts[0],
                'cls': '.'.join(cparts[1:]),
                'count': cnt,
            })
    candidates.sort(key=lambda x: x['count'], reverse=True)

    # 提取每个候选的嵌套字段（策略 1: 静态快照遍历）
    for c in candidates[:20]:
        c['fields'] = self._walk_static_container(c['tag'], c['cls'], static_body)
        # 评分逻辑不变...

    # ... 排序、去重、缓存（保持不变）
```

### 3.4 静态快照下的嵌套字段遍历

```python
def _walk_static_container(self, tag: str, cls: str, static_body, depth: int = 3) -> list:
    """Walk a static container's DOM tree up to `depth` levels, extracting fields.
    
    Returns list of dicts with: name, type, sample, level (indent), children.
    """
    result = []
    
    try:
        containers = static_body.s_eles(f'{tag}.{cls}')
        if not containers:
            return result
        
        first = containers[0]
        self._walk_element(first, result, depth=depth, prefix="")
    except Exception:
        pass
    
    return result

def _walk_element(self, el, result: list, depth: int, prefix: str):
    """Recursively walk a static element, extracting text-bearing children."""
    if depth <= 0:
        return
    
    try:
        children = el.children()
        for child in children:
            tag_name = child.tag
            class_attr = child.attr('class') or ''
            
            # 判断是否为嵌套容器
            grandchildren = child.children()
            has_text_children = False
            for gc in grandchildren:
                if gc.text and gc.text.strip():
                    has_text_children = True
                    break
            
            # 如果有嵌套文本子节点 → 递归展开
            if has_text_children and depth > 1:
                try:
                    sub_fields = []
                    self._walk_element(child, sub_fields, depth - 1, "")
                    result.append({
                        'name': f"{tag_name}.{class_attr.split()[0] if class_attr else ''}",
                        'type': 'container',
                        'sample': '',
                        'level': 3 - depth,
                        'children': sub_fields,
                    })
                except Exception:
                    pass
            else:
                # 叶子节点
                name = _infer_field_name(class_attr)
                val = (child.text or '').strip()[:46]
                if val:
                    result.append({
                        'name': name,
                        'type': 'text' if tag_name != 'a' else 'href',
                        'sample': val,
                        'level': 3 - depth,
                    })
    except Exception:
        pass
```

### 3.5 降级路径

```
find_containers()
  ├── 策略 1: s_eles() 静态快照
  │     ├── 成功 → 返回嵌套树格式
  │     └── 失败/无结果 → 降级
  ▼
  ├── 策略 2: 批量 JS (来自 #014)
  │     ├── 成功 → 返回格式（单层，但批量）
  │     └── 失败 → 降级
  ▼
  └── 策略 3: 逐次 JS（当前方案，兜底）
```

### 3.6 `scan_by_keyword()` 同理

关键词搜索也应用相同三层策略。但关键词搜索要求动态内容（用户输入的关键词可能匹配 JS 渲染文本），因此**策略 1 跳过**，直接从策略 2 开始。

---

## 四、注意事项

### s_eles() 的局限性（来自 DrissionPage 文档）

> 静态元素没有交互功能，它只是副本，也不会影响原来的动态元素。
> 一个页面中不用反复使用 `s_ele()`，通常只要使用一次。

这意味着：
1. 获取一次静态 body → 全部搜索都在这个副本上完成
2. JS 渲染的动态文本（如 `el.textContent = "xxx"` 通过 JS 设置）在静态快照中不可见
3. `:hover`、`:focus` 伪类状态不可见
4. 事件绑定后的属性变化不可见

对于 web-scout 的场景（页面已经渲染完毕再做扫描），局限性 2/3/4 影响很小。

---

## 五、测试要点

| 场景 | URL | 验证 |
|------|-----|------|
| 静态快照 + 嵌套 | 163.com 首页 | 14x 加速，容器字段含嵌套层级 |
| SPA 页面降级 | B站 | 静态快照可能无结果 → 自动降级 JS |
| 嵌套表格 | 含 `<table>` 页面 | `find_containers` 输出含 `├──` 缩进层级 |
| 嵌套列表 | 含 `<ul>` → `<li>` → `<ul>` 页面 | 二级列表可见 |
| JS 重渲染页面 | 动态加载页面 | 降级到策略 2 或 3 |
| 静态快照空 | 无 `<body>` 页面 | 静默降到策略 2 |

---

## 六、文件改动汇总

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/web_scout/dom.py` | 新增 `_get_static_body()`、`_find_containers_static()`、`_walk_static_container()`、`_walk_element()`；重写 `find_containers()` 为三策略尝试；调整 `_format_elements()` 输出嵌套格式 | ~150 行 |
