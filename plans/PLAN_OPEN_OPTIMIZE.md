# scout_open Fetch 优化计划

> **先监听, 再导航**：DrissionPage 的 `listen.start()` 必须在触发请求的动作之前调用，否则该动作产生的数据包无法捕获。`scout_open` 需要捕获页面初始加载的 API 请求，监听器必须在 `browser.open(url)` 之前启动。

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
text = result["text"]
elements = _ax_summary(state._browser.get_current_tab())

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

### 方案：scout_open 新增 `reuse` 参数

`scout_open` 新增可选参数 `reuse: bool = False`，控制是否复用已有的浏览器 session。

| `reuse` | 行为 | 适用场景 |
|---------|------|---------|
| `False`（默认） | `new_env()` 关闭旧进程，启动全新浏览器 | 防止跨 MCP session 串数据 |
| `True` | 附到已有浏览器，保留登录态和标签页 | 同一 session 内复用（调试/连跑） |

### 工具签名

```python
@state.mcp.tool()
def scout_open(url: str, reuse: bool = False) -> str:
```

### 实现流程

```python
@state.mcp.tool()
def scout_open(url: str, reuse: bool = False) -> str:
    # ① 清理接管来的旧浏览器（除非明确要复用）
    if not reuse:
        if state._browser and state._browser._browser:
            try:
                if state._browser._browser.states.is_existed:
                    state._browser._browser.quit(timeout=3, force=True)
            except Exception:
                pass
            state._browser = None
            state._monitors.clear()
            state._dom_scanners.clear()
            state._login = None
            state._login_pending = False

    # ② 正常流程
    if not state._browser:
        state._browser = BrowserSession(force_new=not reuse)

    monitor = NetworkMonitor(state._browser.get_current_tab())
    monitor.start()
    # ... 导航、等待、返回 AXTree 输出
```

### BrowserSession 改动

```python
class BrowserSession:
    def __init__(self, force_new: bool = False):
        self._browser: Chromium | None = None
        self._tabs: dict[str, dict] = {}
        self._current_tab: str | None = None
        self._next_tab_num: int = 1
        self._force_new = force_new    # <-- 新增

    def _ensure_browser(self) -> Chromium:
        if not self._force_new and self._browser and self._browser.states.is_alive:
            return self._browser

        # ... 原有端口扫描逻辑 ...

        if self._force_new:
            co = ChromiumOptions().new_env()   # 关闭旧进程 + 全新启动
        else:
            co = ChromiumOptions().set_local_port(p)  # 附到已有或启动新的

        self._browser = Chromium(co)
        return self._browser
```

### 改动范围

| 文件 | 改动 |
|------|------|
| `tools/navigate.py` | 新增 `_ax_summary()` + `scout_open` 改签名 + 清理逻辑 |
| `browser.py` | `BrowserSession.__init__` 接受 `force_new` 参数 |
| `browser.py` | `_ensure_browser()` 分支使用 `new_env()` |

### 影响

- 改 `tools/navigate.py` 和 `browser.py`
- 0 新依赖，0 新文件，0 新环境变量
- `reuse=False` 向后兼容（旧行为会多杀一次旧进程，但结果一致）
- `reuse=True` 保留现有行为不变（附到已有浏览器）

### 验证步骤

1. `scout_open("https://www.bilibili.com")` — 默认 `reuse=False`，启动全新浏览器
2. 关闭 MCP / 断开连接，再 `scout_open("...")` — `new_env()` 关掉旧进程，打开新的
3. `scout_open("...", reuse=True)` — 附到已有浏览器，不重置状态
4. 验证 `tab_ids` 和 `_tabs` 同步（不在测试覆盖时出现 `_tabs=2, tab_ids=7`）
