# scout_act — 链式动作优化计划

> **先监听, 再导航**：DrissionPage 的 `listen.start()` 必须在触发请求的动作之前调用，否则该动作产生的数据包无法捕获。`scout_act` 的每个操作（输入/点击/滚动）都可能触发 API 请求，监听器必须在操作前已启动。

## 当前状态

`scout_act` 只支持 `search` / `scroll` 两种单步操作。`scout_click` 是独立工具。

## 优化方案

**一次调用跑多个动作链，统一四种操作为一个工具。**

### 工具签名

```python
@state.mcp.tool()
def scout_act(
    action: str = "",
    value: str | None = None,
    target: str | None = None,
    actions: list | None = None,
) -> str:
```

两种调用方式：

**单步（兼容旧接口）：**
```python
scout_act("scroll", "bottom")
scout_act("input", "python教程", "搜索")
scout_act("click", "下一页")
scout_act("select", "最多播放", "综合排序")
```

**链式（新接口）：**
```python
scout_act(actions=[
    {"action": "input", "value": "python教程", "target": "搜索"},
    {"action": "scroll", "value": "bottom"},
    {"action": "click", "target": "最多播放"},
    {"action": "select", "value": "最近一周", "target": "全部日期"},
])
```

### 四种操作

| action | value | target | 行为 |
|--------|-------|--------|------|
| `input` | 输入内容 | 搜索框文本 | 定位输入框→清空→输入→回车 |
| `scroll` | `bottom`/`top`/`down`/`up`/像素 | 可选容器 CSS | 滚动页面或容器 |
| `click` | — | 元素的可见文本 | 找文本匹配的元素→点击 |
| `select` | 选项文本 | 下拉框文本 | 点下拉→点选项 |

### target 定位规则

`target` 用可见文本定位——和 `scout_elements` 的 Common Actions 输出对齐。AI 不需要记 CSS selector。

```python
def find_el_by_text(tab, text, tags="a,button,input,select,span"):
    for tag in tags.split(','):
        for el in tab.eles(f'tag:{tag}'):
            try:
                if not el.states.is_displayed: continue
                combined = (el.text or '') + ' ' + (el.attr('placeholder') or '') + ' ' + (el.attr('aria-label') or '')
                if text in combined:
                    return el
            except: pass
    return None

def do_input(tab, value, target):
    el = find_el_by_text(tab, target, "input,textarea")
    if not el: return f"Input '{target}' not found"
    el.click(); time.sleep(0.3)
    el.clear(); el.input(value)
    tab.actions.key_down('ENTER').key_up('ENTER')
    return f"Input '{value}' into '{target}'"

def do_scroll(tab, value):
    if value == "bottom": tab.scroll.to_bottom()
    elif value == "top": tab.scroll.to_top()
    elif value and value.lstrip("-").isdigit():
        px = int(value)
        if px >= 0: tab.scroll.down(px)
        else: tab.scroll.up(abs(px))
    return f"Scrolled {value}"

def do_click(tab, target):
    el = find_el_by_text(tab, target, "a,button,span")
    if not el: return f"Click '{target}' not found"
    el.click()
    return f"Clicked '{target}'"

def do_select(tab, value, target):
    el = find_el_by_text(tab, target, "a,button,div")
    if not el: return f"Select trigger '{target}' not found"
    el.click(); time.sleep(0.3)
    opt = find_el_by_text(tab, value, "a,li,span,option")
    if not opt: return f"Option '{value}' not found"
    opt.click()
    return f"Selected '{value}' in '{target}'"
```

### API 追踪

每一步后调用 `pool.step(3.0)` 收新 API。记录步前后的 API 列表，取差集得到本步新增的 API，**将 method + path 直接列在步描述下方**，让 AI 一步到位看到结果，无需再调 `scout_apis()`：

```python
def list_new_apis(records_before: set, records_after: list) -> list[dict]:
    """返回步执行期间新增的 API 记录."""
    before_paths = {(r["method"], r["path"]) for r in records_before}
    return [r for r in records_after
            if (r["method"], r["path"]) not in before_paths]


for a in actions:
    before = list(pool.api_records)
    result = do_action(a)
    pool.step(3.0)
    new_apis = list_new_apis(before, pool.api_records)
    report += f"  [{a['action']}] {result} → +{len(new_apis)} new APIs\n"
    for api in new_apis[:6]:
        method = api["method"].ljust(6)
        report += f"    {method} {api['path']}\n"
    if len(new_apis) > 6:
        report += f"    ... and {len(new_apis) - 6} more\n"
```

输出示例：

```
[5F207A] Action chain (4 steps):

  [input] Input 'python教程' → '搜索' → +8 new APIs
    GET    /x/web-interface/search/all/v2?keyword=python教程
    POST   /x/web-interface/wbi/index/popular
    POST   /x/web-interface/wbi/index/recommend
    GET    /x/web-interface/search/result?keyword=python教程&page=1
    ...

  [scroll] Scrolled to bottom → +11 new APIs
    GET    /x/web-interface/search/result?keyword=python教程&page=2
    GET    /x/web-interface/search/result?keyword=python教程&page=3
    ...

  [click] Clicked '最多播放' → +6 new APIs
    GET    /x/web-interface/search/result?keyword=python教程&order=click
    ...

  [select] Selected '最多播放' in '综合排序' → +3 new APIs
    GET    /x/web-interface/search/result?keyword=python教程&order=click
    ...

Total: 28 new APIs across 4 actions.
```

**规则**：每步最多列 6 条 API，超出的用 `... and N more` 省略，长度可配。

### 性能

- 元素定位：每步 ~100ms（遍历 DOM 找文本）
- sleep 替换为事件等待：等 pool 收到新 API 就继续，不等满 1.5s
- 总耗时 ~6s（B站 4 步，原需 ~15s）

### scout_click 退役

`scout_click` 不再单独存在——`scout_act("click", target="下一页")` 替代。

### 改动文件

| 文件 | 改动 |
|------|------|
| `tools/act.py` | 重写 `scout_act`，新增链式支持 |
| `tools/observe.py` | 删除 `scout_click` |
