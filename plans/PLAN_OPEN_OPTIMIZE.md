# scout_open Fetch 优化计划

## 目标

优化 `scout_open` 的页面信息输出，用 AXTree 替代纯 innerText，单次 open 同时获得页面文本和可交互元素。

## 当前状态

```
scout_open(url)
  → _time.sleep(3)
  → tab.run_js("document.body.innerText")
  → 返回: 743 字纯文本（B站首页），无链接、无控件信息
```

AI 要额外调 `scout_fetch` 拿链接、`scout_elements` 看控件。三步变一步。

## 优化方案

**innerText + AXTree 双输出**，不新增依赖，不新增工具。

### 输出格式

```
[Tab #1] https://www.bilibili.com/
Page opened: 哔哩哔哩 (゜-゜)つロ 干杯~-bilibili

=== Page Text ===
首页 番剧 直播 ... 视频标题 播放量 ...

=== Elements ===
[link] 动态 -> https://t.bilibili.com/
[link] 热门 -> https://www.bilibili.com/v/popular/all
[link] 实话！重庆人真心挚爱... 54.2万 -> https://www.bilibili.com/video/BV...
[textbox] 初音未来缤纷舞台
[button] 换一换
[StaticText] 首页
```

### 实现代码

```python
def _ax_summary(tab) -> str:
    """Extract visible interactive elements from AXTree."""
    result = tab.run_cdp('Accessibility.getFullAXTree')
    nodes = result.get('nodes', [])
    lines = []
    for n in nodes:
        if n.get('ignored', False):
            continue
        name = n.get('name', {}).get('value', '')
        if not name or len(name) < 2:
            continue
        role = n.get('role', {}).get('value', '')
        # Get URL for links
        url = ''
        for p in n.get('properties', []):
            if p.get('name') == 'url':
                url = p.get('value', {}).get('value', '')
                break
        if url:
            lines.append(f'[{role}] {name} -> {url}')
        else:
            lines.append(f'[{role}] {name}')
    return '\n'.join(lines)
```

### scout_open 改动

```python
# 替换原有的纯文本返回
text = result["text"]                                     # innerText（保留）
elements = _ax_summary(state._browser.get_current_tab())  # AXTree（新增）

return "\n".join([
    state.prefix(tab_num),
    f"Page opened: {result['title'] or url}",
    "",
    "=== Page Text ===",
    text,
    "",
    "=== Elements ===",
    elements,
])
```

`_ax_summary()` 在 `_time.sleep(3)` 之后调用，利用等待期间页面已完成渲染。

## 性能

| 方法 | 耗时 | 内容 |
|------|------|------|
| innerText（当前） | 3ms | 743 字纯文本 |
| AXTree（新增） | 110ms | 7640 字含链接 URL + 角色标签 |
| **合计** | **~113ms** | 文本 + 结构化控件 |

在 `sleep(3s)` 之后执行，对用户感知无额外延迟。

## 浏览器复用 Bug 修复

### 问题

DrissionPage 的默认行为：程序结束时浏览器不会主动关闭。MCP 重启后 `Chromium()` 接管旧浏览器（9222 端口仍被占用），但 `BrowserSession._tabs` 是新建的空字典，导致：

1. 旧标签页在 `_tabs` 中无记录 → `scout_tabs` 看不到它们
2. 旧标签页在 `_monitors` 中无 monitor → API 监听失效
3. `_next_tab_num` 从 1 重新开始 → 编号与浏览器实际标签页冲突

### 关键 API（来源：DrissionPage 文档）

| API | 作用 |
|-----|------|
| `browser.states.is_existed` | 是否接管已有浏览器（非本程序创建） |
| `browser.tab_ids` | 所有标签页 ID 列表 |
| `browser.get_tab(id)` | 按 ID 或序号获取标签页对象 |
| `browser.reconnect()` | 断开并重新连接浏览器 |
| `ChromiumOptions().new_env()` | 强制启动全新浏览器（关闭旧进程） |

### 修复方案

`scout_open` 调用时检测并清理残留浏览器，然后重建 `BrowserSession`：

```python
def scout_open(url: str) -> str:
    # ① 检测并清理接管来的旧浏览器
    if state._browser and state._browser._browser:
        if state._browser._browser.states.is_existed:
            state._browser._browser.quit(timeout=3, force=True)
            state._browser = None
    # ② 正常流程继续...
    if not state._browser:
        state._browser = BrowserSession()
```

`BrowserSession()` 重建后 `_tabs = {}`、`_monitors` 在 scout_close 或首次 open 时也重建。

### 改动范围

- 改 `tools/navigate.py` 的 `scout_open`，在第一步加清理

## 影响

- 改 `tools/navigate.py`，新增 `_ax_summary()` 函数 + `scout_open` 首步清理逻辑
- 0 新依赖，0 新文件，0 新环境变量
- 不删除 `scout_fetch` 和 `scout_elements`（保留供深度使用）
