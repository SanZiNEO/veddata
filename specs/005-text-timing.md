# 005: 页面文本时序 — 等待 DOM 稳定后提取文本

> **来源**: ROADMAP.md 已知问题 #5 + 规划中 "等待策略优化"
> **优先级**: P1（与 #0 联动，已在 #0 设计中包含）
> **独立文件原因**: 这是 ROADMAP 中显式列出的独立问题，需要验证和测试清单

---

## 一、问题诊断

当前 `browser.py` 的 `open()` 方法在 `tab.get(url)` 返回后立即调用 `get_text()`：

```python
# browser.py:46-61 (现状)
def open(self, url: str) -> dict:
    self.tab.get(url)           # 等待文档加载完成
    title = self.tab.title
    text = self.get_text()      # 立即提取 — 可能 DOM 未稳定
    ...
```

**时序问题**：

```
时间线:
  t0: tab.get(url) 开始
  t1: 主文档加载完成（DrissionPage 的 page_load 事件触发）
  t2: tab.get() 返回 ← get_text() 在这一刻执行
  t3: JS 框架渲染完成（React/Vue hydration）
  t4: 异步数据加载完成（豆瓣阅读数等懒加载内容）

问题: get_text() 在 t2 执行，拿不到 t3/t4 的内容
```

**受影响的页面类型**：

| 页面类型 | 典型站点 | 丢失内容 |
|---------|---------|---------|
| SSR + 客户端 hydration | 豆瓣话题广场 | 阅读数、回复数 |
| 纯 SPA（React/Vue） | B 站、知乎 | 整个页面内容可能为空或只有 loading spinner |
| 异步渲染列表 | 微博、Twitter | 时间线内容未加载 |
| 无限滚动首页 | 小红书、Instagram | 初始卡片未渲染 |

---

## 二、解决方案

### 已在 #0 设计中实现

在 `browser.py` 的 `open()` 中，`tab.get(url)` 之后、`get_text()` 之前插入 DOM 稳定等待：

```python
# browser.py — 新 open() 方法（与 #0 设计一致）
def open(self, url: str) -> dict:
    self.tab.get(url)
    
    # 等待 DOM 稳定 — 新增
    try:
        self.tab.wait.eles_loaded('a, button, input', timeout=5, any_one=True)
    except Exception:
        pass  # 纯文本/停服公告页可能没有任何交互元素
    
    title = self.tab.title
    text = self.get_text()
    ...
```

### 为什么选择 `wait.eles_loaded('a, button, input', any_one=True)`

| 策略 | 评价 |
|------|------|
| `time.sleep(3)` | 固定延迟，浪费 3 秒，DOM 可能仍未就绪 |
| `tab.wait.doc_loaded()` | 等价于 `tab.get()` 的默认行为，多此一举 |
| `tab.wait.load_start()` | 只在点击跳转时有用，`get()` 已内置 |
| `tab.wait.eles_loaded('a, button, input', any_one=True)` | **最佳** — 等待任意一个交互元素出现即返回；哑页面自动跳过 |

**DrissionPage API**（来自 waiting 文档）：

```
tab.wait.eles_loaded(locator, timeout, any_one=False)
  - 等待指定的一个或多个元素在 DOM 中加载
  - any_one=True: 任意一个出现即返回（不等待全部）
  - timeout: 超时时间，默认 10s，这里设 5s 加快对哑页面的 fallback
```

### 为什么不追求完美时序

对于 `scout_open` 的目的（AI 读文本判断页面是否可用），只要 80% 的页面内容已渲染即可。像豆瓣阅读数这种具体的数字，对可用性判断没有影响。如果需要完整内容，AI 可以在 `scout_open` 返回后，通过 `scout_action("search"/"scroll")` 触发加载，再用 `scout_list_apis` 查看数据。

---

## 三、与 #0 的关系

| 问题 | 处理位置 | 状态 |
|------|---------|------|
| #0 `scout_open` 拆分 | `server.py` 重写 | 独立 |
| #5 文本时序 | `browser.py` `open()` 增加等待 | 包含在 #0 设计中 |

两者可同时实现。`#5` 的改动是 `browser.py` 一行代码，`#0` 的改动在 `server.py`。由于 #0 的 `scout_open` 调用 `browser.open()`，只要先改 `browser.open()`，两边的修改自然衔接。

---

## 四、测试要点

| 场景 | URL | 验证方式 |
|------|-----|---------|
| SSR 页面 | 豆瓣话题广场 | `scout_open` → 输出的文本包含话题标题和至少部分帖子内容 |
| SPA 页面 | B 站首页 | `scout_open` → 文本不为空，不全是 loading/skeleton 占位符 |
| 停服公告 | 富途停服 URL | `scout_open` → 完整显示公告文本 |
| 纯登录页 | 各种 /login | `scout_open` → 显示登录提示文本 |
| 网络慢 | 模拟慢网络 | 5s 超时内返回文本（可能是部分文本），不卡死 |
| 无交互元素页 | 纯 JSON 接口页 | `wait.eles_loaded` 超时，静默 catch 后仍然返回文本 |

---

## 五、文件改动汇总

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/web_scout/browser.py` | `open()` 方法中 `tab.get(url)` 之后增加 `tab.wait.eles_loaded()` | ~4 行 |
