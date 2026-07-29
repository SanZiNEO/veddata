# Web Scout v1.0 — Playwright 重构计划

> 核心目标：将 Web Scout 从"网页查看工具"重新定义为**数据源发现与分析工具**。
> AI 应该能像人开 DevTools 一样：看 DOM 树 → 找到数据源 → 打断点看数据 → 追踪值流向。

---

## 目录

1. [现状与问题](#1-现状与问题)
2. [新架构总览](#2-新架构总览)
3. [数据呈现原则](#3-数据呈现原则--不贴标签只描述来源)
4. [Phase 1: 浏览器层移植](#4-phase-1-浏览器层移植)
5. [Phase 2: DOM 目录树](#5-phase-2-dom-目录树)
6. [Phase 3: 网络监听 + 数据捕获](#6-phase-3-网络监听--数据捕获network_monitorpy)
7. [Phase 4: 请求断点系统](#7-phase-4-请求断点系统)
8. [Phase 5: 值追踪器](#8-phase-5-值追踪器)
   9.7 [工具描述策略](#97-工具描述策略--让-ai-不再拿它当浏览器用)
11. [实施顺序](#11-实施顺序)
12. [文件结构](#12-文件结构)

---

## 1. 现状与问题

### 1.1 当前架构

```
browser.py          ← DrissionPage Chromium 封装
network_pool.py     ← tab.listen.start() 轮询监听
requester.py        ← SessionPage 发请求（和浏览器分离）
dom.py              ← tab.run_js() 扫描
login.py            ← tab.cookies() 检测
```

### 1.2 核心矛盾

当前工具的**返回语义**和**实际用途**不匹配：

| 方面 | 现在的表现 | 应该做的事 |
|------|-----------|-----------|
| 定位 | "网页查看工具" | **数据源发现工具** |
| goto 返回 | 网页文本摘要 + API 列表 | **这个页面有哪些数据、分别在什么位置、怎么触发的** |
| API 捕获 | 一个列表，全是"XHR" | **每条数据记录触发时机 + 数据结构，不贴类型标签** |
| 断点 | 没有 | **请求在途中暂停，AI 查看数据后决定放行/修改/中止** |
| 值追踪 | `scout_search` 只搜 API 响应体 | **不仅搜网络请求，还搜 DOM 内嵌、JS 变量、WebSocket** |

### 1.3 DrissionPage 的硬限制

| 功能 | DrissionPage | Playwright |
|------|:------------:|:----------:|
| 请求拦截 (`route`) | ❌ | ✅ |
| 请求级断点（暂停 + 等 AI 决策） | ❌ | ✅ async handler |
| 修改请求/响应 | ❌ | ✅ route.continue_/fulfill |
| 事件驱动监听 | ❌ 轮询 | ✅ page.on("request" / "response") |
| CDPSession 深层控制 | ⚠️ run_cdp 单次 | ✅ 持久 session |
| 精确等待（等某请求完成） | ❌ listen.wait 盲等 | ✅ page.wait_for_response |
| WS 拦截 | ❌ | ✅ CDP Fetch.enable |
| 多浏览器/多 context | ⚠️ 有限 | ✅ browser.contexts |

---

## 2. 新架构总览


```
┌─────────────────────────────────────────────────────┐
│                    MCP Tools                          │
│  scout_open  scout_goto  scout_act  scout_breakpoint  │
│  scout_dom_tree  scout_inspect  scout_trace_value     │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                  Event Bus                            │
│   page.on("request")  →  记录请求信息 + 触发来源      │
│   page.on("response") →  记录响应体 + 字段结构        │
│   page.evaluate()     →  扫描 DOM 内嵌数据 + JS 变量  │
└──────┬──────────┬──────────┬──────────┬─────────────┘
       │          │          │          │
┌──────▼──┐ ┌─────▼─────┐ ┌─▼──────┐ ┌─▼───────────┐
│browser  │ │network    │ │dom     │ │breakpoint    │
│(PW)     │ │monitor    │ │scanner │ │engine        │
│Chromium │ │event-driven│ │tree    │ │route handler │
│tab ctx  │ │+trigger    │ │+值提取  │ │+ pause queue │
│         │ │tracking    │ │        │ │              │
└─────────┘ └───────────┘ └────────┘ └──────────────┘
```

核心变化：

- **browser.py** — DrissionPage → Playwright async
- **network_monitor.py** — 从轮询改为事件驱动，记录触发上下文，不贴类型标签
- **dom.py** — 新增 DOM 目录树生成，替代「交互元素 + 容器 + common actions」三块拼凑
- **requester.py** — SessionPage → httpx
- **breakpoint.py** — 全新模块：route handler + 暂停队列 + AI 决策接口

---

## 3. 数据呈现原则 — 不贴标签，只描述来源

### 3.1 问题

现在的 `network_pool.py` 在记录数据包时会标 `resourceType: XHR / Fetch / Script`。上一版计划里我写了五类分类标签（Type A/B/C/D/E）——你说了之后我想明白了，这些都是**诱导性标注**。

AI 看到 "SSR 数据" 它就会往 SSR 的方向想，看到 "surface API" 它就会觉得这个是主数据源。**标签本身在限制 AI 的判断。**

### 3.2 原则

**只描述事实，不下结论。**

| 不要这样 | 要这样 |
|---------|-------|
| 来源类型: SSR 内嵌数据 | 位置: `<script id="__NEXT_DATA__">` |
| 来源类型: 明面 API | 触发: 页面加载时自动发起 / URL: `/api/list` |
| 来源类型: JS 内部变量 | 位置: `window.__INITIAL_STATE__` |
| 来源类型: 流式传输 | 协议: WebSocket / 连接: `wss://push.example.com` |
| resourceType: XHR | （不标，让 AI 自己看 URL 和方法判断） |

### 3.3 描述维度

每条捕获到的数据，用三个维度描述：

```
1. 位置/来源       — 在哪里找到的（DOM 节点、网络请求、变量名）
2. 触发方式       — 什么时候、因为什么操作产生的（页面加载 / 点击按钮 / 滚动到底）
3. 数据结构       — 有哪些字段、类型是什么
```

没有"类型标签"，没有分类优先级。只是**陈列事实**。

### 3.4 返回语义

`scout_goto` 现在的返回是 "网页文本摘要 + API 列表"。
应该改为 "DOM 目录树 + 数据源清单"，每条数据源不带类型标签，只描述位置和触发：

```
[Tab 5F207A] https://example.com
Title: XX 网站

=== DOM Tree ===
div#app
├── header → nav → a[href="/"] "首页"
├── main.content
│   ├── div#__NEXT_DATA__               ← 包含 JSON: {page, user, posts}
│   └── div.post-list
│       └── article.post x30
│           ├── h2.title "文章标题"
│           └── div.meta "2024-01-01"
└── footer

=== Captured Data (4 items) ===
[1] GET /api/post/list → ?page=1&size=20
    触发: 页面加载时自动发起
    响应: {items: [...], total: 100} → id, title, author, date

[2] 内嵌数据 → <script id="__NEXT_DATA__">
    触发: 页面 HTML 加载时
    内容: {page: 1, user: {...}, posts: [...]} → 12 个字段

[3] POST /api/auth → {token}
    触发: 页面加载时自动发起
    响应: {uid: 123, name: "xxx", avatar: "url"}

[4] WebSocket → wss://push.example.com/feed
    触发: 页面加载时建立连接
    状态: 已连接，等待消息

=== Actions ===
输入框  input#keyword  placeholder="搜索"
按钮    button.load-more  text="加载更多"
  → 操作后捕获到 [1] 的参数变化: page=2
```

**没有"SSR"、"XHR"、"API"这些词。只是说"这个数据在这"、"那个是加载时触发的"。**

---

## 4. Phase 1: 浏览器层移植

### 4.1 browser.py 重写

```python
# 新的 browser.py
# DrissionPage.Chromium → playwright.async_api.Browser
# 保持对外接口不变，内部全换

class BrowserSession:
    def __init__(self):
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None  # 一个 context = 一个 session
        self._pages: dict[str, Page] = {}            # tab_id → Page
        self._current_page: str | None = None
```

### 4.2 变化点

| 当前 (DrissionPage) | 改后 (Playwright) |
|---------------------|------------------|
| `ChromiumOptions().set_local_port(p)` | `playwright.chromium.launch(port=p)` |
| `Chromium(co)` | `await playwright.chromium.launch_persistent_context(...)` |
| `tab.get(url)` | `await page.goto(url)` |
| `tab.run_js(js)` | `await page.evaluate(js)` |
| `tab.run_cdp(cmd)` | `await page.context.new_cdp_session(page)` |
| `tab.cookies()` | `await page.context.cookies()` |
| `tab.listen.start()` | `page.on("response", handler)` |
| `tab.listen.wait(timeout)` | 事件驱动，不需要轮询 |
| `tab.close()` | `await page.close()` |
| `tab.scroll.to_bottom()` | `await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")` |
| `tab.eles(tag:tag)` | `await page.locator(tag).all()` |
| `tab.actions.key_down('ENTER')` | `await page.keyboard.press('Enter')` |

### 4.3 Session 管理

Playwright 的 **BrowserContext** 对应一个独立的浏览器 session（cookie、storage、缓存隔离）。

```
Browser
├── Context 1  ← Web Scout 用这个
│   ├── Page A (tab 1)
│   └── Page B (tab 2)
└── Context 2  ← 可选：以后支持多 session 隔离
```

### 4.4 关键决策：同步 vs async

Playwright Python 支持同步和 async 两种 API。

**建议用 async**，因为：
- `route()` handler 需要 `await`（AI 决策时暂停）
- 事件监听是异步的
- CDPSession 是全异步
| `tab.eles(tag:tag)` | `await page.locator(tag).all()` |
| `tab.actions.key_down('ENTER')` | `await page.keyboard.press('Enter')` |
| `SessionPage().get(url)` (requester.py) | `httpx.get(url, cookies=..., headers=...)` |
| `page.set.cookies()` (requester.py) | `httpx.Client(cookies=...)` |

**方案 A：工具内跑 asyncio.run()**（推荐，最低侵入）
```python
@mcp.tool()
def scout_goto(url: str):
    return asyncio.run(_async_goto(url))

async def _async_goto(url):
    ...  # 全异步逻辑
```

**方案 B：FastMCP 的 async 支持**
```python
@mcp.tool()
async def scout_goto(url: str):
    ...  # 如果 FastMCP 支持
```

方案 A 更保守，先跑通再优化。

---

## 5. Phase 2: DOM 目录树

### 5.1 目标

替代当前的 `scout_elements()`（三块拼凑：交互元素 + 容器 + common actions），建立一个**在内存中持有、可查询**的 DOM 结构模型。

和浏览器的区别：
- 浏览器的 Elements 面板是实时 DOM，操作会同步到页面
- 我们的内存树是**快照**——在页面稳定后拍一张，转成结构化数据存在 Python 进程里，后续搜索、定位都在内存操作，不再调 JS

### 5.2 内存数据结构

```python
class DOMNode:
    tag: str           # div, span, a, button, input, h2, ...
    id: str            # DOM id
    classes: list[str] # class 列表
    text: str          # 可见文本（截断到 80 字）
    attrs: dict        # 关键属性：href, src, placeholder, aria-label, ...
    rect: dict | None  # 尺寸位置 {width, height, top, left}（仅可见元素）
    children: list[DOMNode]
    collapsed: bool    # 折叠标记（连续同类、不可见、空节点）
    collapsed_count: int  # 折叠了几个同类兄弟
    
class DOMTree:
    root: DOMNode
    tab_id: str
    captured_at: float  # 快照时间戳
    
    def search(self, text: str) -> list[DOMNode]:
        """在内存树中搜文本，不调浏览器"""
    
    def find_tag(self, tag: str) -> list[DOMNode]:
        """按标签找元素"""
    
    def find_attr(self, key: str, value: str = "") -> list[DOMNode]:
        """按属性找"""
    
    def locate(self, path: str) -> DOMNode | None:
        """通过路径定位：div.content > div.post-list > article:nth-child(3)"""
    
    def format(self, depth: int = 4) -> str:
        """输出给 AI 看的文本树"""
```

### 5.3 快照过程

```
scout_goto(url)  或  scout_dom_tree()
  ↓
page.evaluate(js) → 从 document.body 递归遍历
  ↓
序列化为 JSON → 传到 Python 端
  ↓
反序列化为 DOMTree 对象 → 存到 state._dom_trees[tab_id]
  ↓
scout_dom_tree() 直接从内存读，不再调浏览器
```

### 5.4 输出格式（给 AI 看）

```
=== DOM Tree ===
div#app
├── header.site-header
│   ├── a.logo[href="/"] "MyApp"
│   ├── nav.main-nav
│   │   ├── a[href="/explore"] "发现"
│   │   ├── a[href="/following"] "关注"
│   │   └── input#search[placeholder="搜索用户/内容"]
│   └── div.user-menu
│       └── a[href="/profile"] "用户名"
├── main.content
│   ├── div.post-feed                       [x25]
│   │   ├── article: h2.title "文章标题"     [field]
│   │   ├── article: div.meta "2024-01-01"  [field]
│   │   └── ...
│   └── button.load-more "加载更多"
└── footer
    └── span.copyright "© 2024"
```

### 5.5 工具集

```python
@mcp.tool()
def scout_dom_tree(
    depth: int = 4,
    tab: str = "",
) -> str:
    """输出当前页面的 DOM 目录树（从内存读）。
    
    首次调用或页面导航后会自动重新扫描。
    返回的树上标有容器、字段、交互元素的位置。
    """

@mcp.tool()
def scout_dom_search(
    text: str,
    tab: str = "",
) -> str:
    """在内存 DOM 树中搜索文本。
    
    不调浏览器，直接在保存的树结构里查找。
    返回匹配的节点路径和上下文。
    """

@mcp.tool()
def scout_dom_locate(
    path: str,
    tab: str = "",
) -> str:
    """通过路径定位一个 DOM 节点。
    
    path 格式: div.content > div.post-list > article:nth-child(3)
    返回该节点的完整子树。
    """
```

### 5.6 生命期

| 事件 | 行为 |
|------|------|
| `scout_goto` | 重新扫描，覆盖旧树 |
| `scout_tab_switch` | 如果目标 tab 有缓存的树就用缓存，没有就自动扫 |
| `scout_act("click", ...)` | 不自动重扫（点击可能改变 DOM，但 AI 需要时手动调 scout_dom_tree） |
| `scout_tab_close` | 删除该 tab 的树 |
| `scout_close` | 清空所有树 |

替换当前的 `scout_elements()`。

---

## 6. Phase 3: 网络监听 + 数据捕获（network_monitor.py）

### 6.1 目标

当前 `network_pool.py` 靠 `tab.listen.wait()` 轮询，只收 XHR/Fetch，记录 `resourceType`。

新版去掉轮询、去掉类型标签，改为纯事件驱动，只做三件事：

```
page.on("request")     → 记录：谁发起的、URL、方法、参数
page.on("response")    → 记录：响应体、字段结构、状态码
page.evaluate(js)      → 扫 DOM 和全局变量，发现内嵌数据
```

**没有"分类"。** 一条记录就是一条记录，AI 自己看 URL、触发时机、数据结构去判断。

### 6.2 触发上下文

关键设计：每条捕获到的数据都带上 **"怎么来的"** 信息：

| 信息 | 说明 | 来源 |
|------|------|------|
| `source` | URL 或 DOM 位置 | request.url / 节点 id |
| `method` | HTTP 方法 | request.method |
| `trigger` | 触发时机描述 | 页面加载 / 点击按钮 / 滚动 |
| `timestamp` | 捕获时间 | time.time() |
| `request_headers` | 请求头 | request.headers |
| `response_body` | 响应体 | response.json() |
| `field_count` | 字段数 | 递归计数 |
| `response_headers` | 响应头头 | response.headers |

没有 `resourceType`、没有 `source_type`、没有 `category`。

### 6.3 事件驱动代码

```python
class NetworkMonitor:
    def __init__(self):
        self.records: list[dict] = []
        self._pending = asyncio.Queue()
    
    def attach(self, page):
        """绑定到 Page 的事件"""
        page.on("request", self._on_request)
        page.on("response", self._on_response)
    
    async def _on_request(self, request):
        """记录请求信息，不分类"""
        # 只记录感兴趣的请求类型
        if request.resource_type not in ("xhr", "fetch", "document", "eventsource", "websocket"):
            return
        self._pending_request[request.url] = {
            "url": request.url,
            "method": request.method,
            "request_headers": request.headers,
            "timestamp": time.time(),
        }
    
    async def _on_response(self, response):
        """记录响应体，带触发上下文"""
        req_info = self._pending_request.pop(response.url, {})
        
        # 只关心 JSON 响应和 HTML (SSR)
        ct = response.headers.get("content-type", "")
        if "json" not in ct and "text/html" not in ct:
            return
        
        body = await self._safe_json(response)
        if body is None:
            return
        
        record = {
            "url": response.url,
            "method": req_info.get("method", "GET"),
            "source": response.url,                    # 来源 URL
            "trigger": "page_load",                     # 触发方式（后期由 act 更新为 "click:加载更多"）
            "timestamp": req_info.get("timestamp", time.time()),
            "request_headers": req_info.get("request_headers", {}),
            "response_status": response.status,
            "response_headers": dict(response.headers),
            "response_body": body,
            "field_count": _leaf_count(body),
        }
        self.records.append(record)
        await self._pending.put(record)
```

### 6.4 内嵌数据扫描（DOM + JS 变量）

不动网络监听的事件流，额外执行两步一次性扫描：

```python
async def scan_embedded(page) -> list[dict]:
    """扫一遍页面，找所有内嵌数据。"""
    results = []
    
    # 1. <script> 里的 JSON 块
    js = """
    const r = [];
    for (const s of document.querySelectorAll('script:not([src])')) {
        const t = (s.textContent || '').trim();
        if (!t) continue;
        try { const p = JSON.parse(t); r.push({id: s.id, keys: Object.keys(p).slice(0,20)}); }
        catch(e) {}
    }
    return r;
    """
    for item in await page.evaluate(js):
        results.append({
            "source": f"<script id='{item['id']}'>",
            "trigger": "html_parse",
            "response_body": item,  # 实际会取完整 JSON
            "field_count": len(item.get("keys", [])),
        })
    
    # 2. window.__xxx__ 全局变量
    vars = await page.evaluate("""
    Object.keys(window).filter(k => k.startsWith('__')).map(k => ({key: k, type: typeof window[k]}))
    """)
    for v in vars:
        results.append({
            "source": f"window.{v['key']}",
            "trigger": "js_global",
            "type_hint": v["type"],
        })
    
    return results
```

### 6.5 触发时机追踪

`scout_act` 在执行每个操作时更新 NetworkMonitor 的触发上下文：

```python
# act.py
def _do_action(tab, monitor, step):
    # 操作前设置触发器
    monitor.set_trigger_context(f"{step['action']}:{step.get('target', '')}")
    # 执行操作
    ...
    # 操作后收新数据
    new_records = monitor.drain_new()
```
这样每条记录都能追溯到 "是点击了什么按钮触发的"。

---

## 7. Phase 4: 请求断点系统

### 7.1 核心流程

这是 Playwright 迁移后最重要的新能力。

```
AI 调 scout_breakpoint("**/api/**")
  ↓
page.route("**/api/**", breakpoint_handler)
  ↓
当匹配的请求发起 →
  breakpoint_handler(route) 被调用
  ↓
route.request 的信息提取并存入暂停队列
  ↓
handler await 一个 Future（等待 AI 决策）
  ↓
AI 通过 scout_paused / scout_inspect_paused / scout_resume 交互
  ↓
handler 拿到决策 → continue / abort / modify / fulfill
```

### 7.2 暂停队列

```python
class BreakpointEngine:
    def __init__(self):
        self._paused: dict[int, PausedRequest] = {}  # id → 暂停的请求
        self._next_id = 1
        self._active_patterns: list[str] = []
    
    async def handler(self, route):
        """注册为 page.route 的回调"""
        req = route.request
        
        # 存起来等 AI 处理
        paused = PausedRequest(
            id=self._next_id,
            route=route,
            method=req.method,
            url=req.url,
            headers=req.headers,
            post_data=await req.post_data() if req.method != "GET" else None,
        )
        self._paused[paused.id] = paused
        self._next_id += 1
        
        # 等 AI 决策（超时后默认放行）
        await paused.decision.wait(timeout=300)
        
        # 执行 AI 的决策
        if paused.action == "continue":
            await route.continue_()
        elif paused.action == "abort":
            await route.abort()
        elif paused.action == "modify":
            await route.continue_(
                headers=paused.modified_headers,
                post_data=paused.modified_body,
            )
        elif paused.action == "fulfill":
            await route.fulfill(
                status=paused.fulfill_status,
                body=paused.fulfill_body,
            )
        
        del self._paused[paused.id]
```

### 7.3 断点工具集

```python
@mcp.tool()
def scout_breakpoint(
    pattern: str = "**/*",
    request_stage: str = "request",  # request / response / both
) -> str:
    """设置请求断点。匹配 pattern 的请求会被暂停等 AI 处理。
    
    pattern: URL 通配符，如 "**/api/**" 或 "**/*.json"
    request_stage: 在请求发出前暂停还是在收到响应后暂停
    """

@mcp.tool()
def scout_paused() -> str:
    """列出所有被断点暂停的请求。"""
    # │ ID │ Method │ URL │ Size │ Status │
    # ├────┼────────┼─────┼──────┼────────┤
    # │  1 │ POST   │ /api/login │ 234B │ waiting │
    # │  2 │ GET    │ /api/list  │ 89B  │ waiting │

@mcp.tool()
def scout_inspect_paused(
    breakpoint_id: int
) -> str:
    """查看一个被暂停的请求的完整详情。
    
    返回: method, url, headers, body, query params
    """

@mcp.tool()
def scout_resume(
    breakpoint_id: int,
    action: str = "continue",  # continue / abort / modify / fulfill
    headers: str = "",         # JSON，仅 modify 时
    body: str = "",            # JSON，仅 modify/fulfill 时
    status: int = 200,         # 仅 fulfill 时
) -> str:
    """对暂停的请求做出决策，让它继续。"""
```

### 7.4 针对 AI 调试的断点语义

回到你之前说的——断点不是为了"卡住"，而是为了**揭示数据**。

所以断点的返回语义应该是：

```
scout_breakpoint("**/api/list") → 已注册
scout_act("click", "加载更多")
  → 触发了断点 #1
    {
      "breakpoint_id": 1,
      "triggered_by": "点击「加载更多」按钮",
      "request": {
        "method": "GET",
        "url": "https://api.example.com/list?page=2",
        "headers": {"Authorization": "Bearer ***"},
      },
      "response_so_far": null,            ← request_stage=request 时无响应
      "data_preview": {                   ← 推断的数据结构
        "page": "number",
        "items": "array[item]",
        "item": {"id": "number", "title": "string"}
      }
    }
```

**核心：断点的价值不是暂停本身，而是它给了 AI 一个"在数据流动的精确时刻停下来仔细观察"的机会。**

---

## 8. Phase 5: 值追踪器

### 8.1 目标

你说的场景：**AI 想知道一个值（比如 `userid`）在这个页面里都流经过了哪些数据源。**

这需要跨数据源搜索：

```
输入: "userid"
输出:
  ├── <script id="__NEXT_DATA__"> → props.pageProps.user.id  = 12345
  ├── GET /api/user/profile → response.user.id  = 12345
  ├── POST /api/auth → request.body.user_id  = 12345
  ├── div.user-info → span#uid → text "12345"
  ├── window.__INITIAL_STATE__.currentUser.id  = 12345
  └── ws://push → message.userId  = 12345
```

### 8.2 实现

```python
@mcp.tool()
def scout_trace_value(
    value: str,
    tab: str = "",
) -> str:
    """全局搜索一个值出现在哪些数据源中。
    
    搜索范围:
    1. SSR <script> JSON 块 → 字段路径 + 值
    2. 已捕获的 API 请求/响应 → 字段路径 + 值
    3. DOM 渲染文本 → 元素路径 + 值
    4. window 全局变量 → 变量路径 + 值
    5. 断点暂停队列中的请求 → 同上
    
    返回按数据源类型分组的命中列表。
    """
```

搜索空间：

| 数据源 | 搜索方法 | 延迟 |
|--------|---------|:----:|
| SSR JSON | `evaluate()` 反序列化 JSON 块 | 10ms |
| 已捕获 API | 本地缓存中 grep | 1ms |
| DOM 文本 | `evaluate("document.body.innerText.includes(val)")` | 5ms |
| DOM 属性 | `evaluate("//*[contains(@*, val)]")` | 20ms |
| window 变量 | `evaluate("JSON.stringify(window.__xxx__)")` | 10ms |
| WebSocket 历史 | 有捕获时才可搜 | — |

不能要求毫秒级返回。对 AI 来说，几百毫秒的搜索完全可接受。

---

## 9. 新工具清单

### 9.1 导航（不变但内部重写）

| 工具 | 变化 |
|------|------|
| `scout_open` | 内部 DrissionPage → Playwright，语义不变 |
| `scout_goto` | 内部重写，返回内容改为数据源分类 + DOM 树 |
| `scout_close` | 不变 |
| `scout_tabs` | 不变 |
| `scout_tab_switch` | 不变 |
| `scout_tab_close` | 不变 |

### 9.2 观察（合并 + 新增）

| 工具 | 变化 |
|------|------|
| `scout_fetch` | 保留（读页面全文） |
| `scout_screenshot` | 保留 |
| `scout_elements` | **删除**，由 `scout_dom_tree` 替代 |
| `scout_cookies` | 保留 |
| **`scout_dom_tree`** | **新增**，结构化 DOM 目录树 |

### 9.3 交互（不变）

| 工具 | 变化 |
|------|------|
| `scout_act` | 内部元素定位从 `_find_el_by_text` → Playwright locator |
| `scout_login` | 保留，`cookies()` API 微调 |

### 9.4 发现（大改）

| 工具 | 变化 |
|------|------|
| `scout_apis` | 保留 |
| `scout_inspect` | 保留 |
| `scout_search` | **增强**：不仅搜网络请求，还搜 DOM 内嵌、JS 变量、WebSocket |
| `scout_context` | **增强**：同上 |
| `scout_export` | 保留 |
| `scout_export_all` | 保留 |
| `scout_peek` | 保留 |
| `scout_request` | 保留，内部从 `SessionPage` → httpx |
| **`scout_breakpoint`** | **新增**，注册请求断点 |
| **`scout_paused`** | **新增**，查看暂停的请求 |
| **`scout_inspect_paused`** | **新增**，查看暂停请求详情 |
| **`scout_resume`** | **新增**，放行/修改/中止暂停请求 |
| **`scout_trace_value`** | **新增**，值追踪器 |

### 9.5 扫描

| 工具 | 变化 |
|------|------|
| `scout_scan` | 保留，扩展 `mode` 参数 |

### 9.6 工具总数变化

| 分类 | 现 | 减 | 增 | 后 |
|------|:--:|:--:|:--:|:--:|
| 导航 | 6 | 0 | 0 | 6 |
| 观察 | 4 | -1 | +1 | 4 |
| 交互 | 2 | 0 | 0 | 2 |
| 发现 | 8 | 0 | +5 | 13 |
| 扫描 | 1 | 0 | 0 | 1 |
| **合计** | **21** | **-1** | **+6** | **26** |

## 9.7 工具描述策略 — 让 AI 不再拿它当浏览器用

### 问题

当前 Web Scout 的工具描述写得"太像浏览器"了。例如 `scout_fetch` 的 docstring 写着 "获取当前页面的完整文本内容"——AI 一看就觉得这是个好用的网页阅读器，遇到"帮我看看这个页面"的需求就优先选它。这不怪 AI。

### 原则：页面访问是手段，数据发现是目的

页面访问能力**必须保留**（做爬虫不可能不看页面），但在工具描述中，它应该被表述为**工作流中的一个前置步骤**，而不是工具的功能主体。

### 改写方案

**改动位置**：每个工具的 FastMCP docstring、README、MCP 配置中的 instructions。

| 工具 | 当前描述（问题） | 改后描述 |
|------|----------------|---------|
| `scout_open` | "Open / manage the browser session." | "**启动数据发现会话**。打开浏览器以开始捕获页面数据源。浏览网页？这是前置步骤，不是终点。" |
| `scout_goto` | "Navigate to a URL and capture API requests." | "**导航到目标页面，自动发现所有数据来源。** 返回 DOM 结构、网络请求、内嵌数据、JS 变量的完整清单。" |
| `scout_fetch` | "Get the full text content of the current page." | "**获取页面全文，辅助定位数据关键词。** 当需要从页面文本中选取关键词来反查 API 时使用。不是浏览器替代品。" |
| `scout_apis` | "List all captured API endpoints." | "**列出已捕获的所有数据。** 包括网络请求、DOM 内嵌数据、JS 变量等。每条记录标注触发时机，不贴类型标签。" |
| `scout_search` | "Search for data by keyword across captured network data." | "**在已捕获的所有数据中搜索关键词。** 包括网络请求、DOM 内嵌 JSON、页面渲染文本和 JS 全局变量。" |
| `scout_peek` | "One-shot API discovery." | "**快速探测指定 URL 的数据源。** 打开页面 → 自动捕获 API → 返回字段文档。" |

### README 和 MCP instructions 也要改

当前 `server.py` 的 `instructions`（FastMCP 的全局说明）开头是 "Web Scout discovers web API endpoints..." 这个方向是对的，但后面跟着的推荐工作流需要调整——**不要第一步就提 "scout_open → scout_goto"，而是第一步就说"这个工具是用来发现数据源的，浏览页面只是手段"。**

关键改动位置：

```
# server.py — FastMCP 的 instructions 字符串
当前: "Web Scout discovers web API endpoints..."
改后: "数据源发现工具，不是浏览器。用于分析页面数据来源、捕获 API、跟踪数据流。"
      "如果你只是要看一个网页，有其他 MCP 工具更合适。"
```

README 当前定位是 "帮助 AI 发现网页数据源的 MCP 服务器——不是爬虫"——这是对的，但需要加一句 **"也不是通用浏览器"**。

---

## 11. 实施顺序

```
Phase 1 ─ 浏览器层移植 (browser.py + network_monitor.py)
  ├── 替换 DrissionPage 依赖为 Playwright
  ├── 重写 browser.py（同步壳包异步）
  ├── 重写 network_monitor.py（事件驱动替代轮询）
  ├── 改 requester.py（APIRequestContext 替代 SessionPage）
  └── 验证：跑通 scout_open → scout_goto → scout_apis → scout_tabs
      [验收: 所有导航工具能用，API 能捕获]

Phase 2 ─ DOM 目录树 (dom.py)
  ├── 新增 JS 递归遍历 DOM → 结构化树
  ├── 容器折叠算法
  └── scout_dom_tree 工具
      [验收: 能产出一棵可读的 DOM 树，包含容器、字段、交互标记]

Phase 3 ─ 网络监听 + 数据捕获 (network_monitor.py)
  ├── 事件驱动替代轮询（page.on request/response）
  ├── 触发上下文追踪（记录每条数据是怎么来的）
  ├── DOM 内嵌数据扫描 (evaluate #__NEXT_DATA__ 等)
  ├── JS 全局变量扫描 (window.__xxx__)
  ├── WebSocket/SSE 检测
  └── scout_goto 返回语义改为不带标签的数据清单
      [验收: goto 返回位置+触发+结构，不贴类型标签]

Phase 4 ─ 断点系统 (breakpoint.py)
  ├── BreakpointEngine（route handler + 暂停队列）
  ├── scout_breakpoint / scout_paused / scout_inspect_paused / scout_resume
  └── 和 scout_act 联动：操作触发断点，查看数据，放行
      [验收: 注册断点 + 触发请求 → AI 查看详情 → 放行/修改]

Phase 5 ─ 值追踪 (scout_trace_value + scout_search 增强)
  ├── 跨数据源搜索逻辑
  ├── scout_trace_value 工具
  └── scout_search / scout_context 扩展为搜全部数据源
      [验收: 追踪一个 userid → 显示它在 SSR/API/DOM/JS 变量各处的值]
```

### 依赖关系

```
Phase 1 ──── 没有前置依赖
Phase 2 ──── 依赖 Phase 1（需要 browser.py 正常工作）
Phase 3 ──── 依赖 Phase 1（需要 Playwright 事件系统）
Phase 4 ──── 依赖 Phase 1（route handler 需要 Playwright）
Phase 5 ──── 依赖 Phase 3（需要所有数据源的捕获能力已就绪）
```

所以开发顺序是 **Phase 1 → (Phase 2 + 3 可并行) → Phase 4 → Phase 5**。

---
## 12. 文件结构

```
src/web_scout/
├── __init__.py
├── server.py              # FastMCP 入口，工具注册（改）
├── state.py               # 全局状态（改，适配 async）
│
├── browser.py             # Chromium 封装（重写，DP → Playwright）
├── network_monitor.py     # 网络监听 + 数据捕获（重写，事件驱动）
├── requester.py           # 请求重放（改，SessionPage → httpx）
├── breakpoint.py          # 断点引擎（新增）
│
├── dom.py                 # DOM 扫描 + 目录树（改，新增 dom_tree 函数族）
├── login.py               # 登录检测（小改，cookies API）
├── export.py              # 导出（不变）
│
└── tools/
    ├── __init__.py
    ├── navigate.py        # open/goto/close/tabs（改，调新 browser API）
    ├── observe.py         # fetch/screenshot/dom_tree/cookies（改，增 dom_tree 删 elements）
    ├── act.py             # act/login（改，元素定位用 PW locator）
    ├── discover.py        # apis/inspect/search/context/export/peek/request
    │                      #   + breakpoint/paused/inspect_paused/resume/trace_value（改+增）
    └── scan.py            # scan（改，扩展 mode 参数）
```

### 增减文件

| 操作 | 文件 |
|------|------|
| **改** | `server.py`, `state.py`, `browser.py`, `dom.py`, `login.py` |
| **改** | `tools/navigate.py`, `tools/observe.py`, `tools/act.py`, `tools/discover.py`, `tools/scan.py` |
| **重写** | `network_monitor.py`（原 `network_pool.py`） |
| **重写** | `requester.py`（`SessionPage` → `httpx`） |
| **新增** | `breakpoint.py` |
| **删除** | `monitor.py`（合并到 `network_monitor.py`） |
| **不改** | `export.py` |

---

## 附录：关键设计决策

### A. 断点超时

暂停的请求不能无限等 AI 决策。默认超时 300 秒，超时后自动 `route.continue_()`。超时时间可通过环境变量 `BREAKPOINT_TIMEOUT` 配置。

### B. 断点列表清空

`scout_open` / `scout_goto` / `scout_close` 时清除所有断点和暂停队列。

### C. 多 Tab 断点

每个 tab 独立注册 route handler，互不干扰。`scout_breakpoint` 接受 `tab` 参数。

### D. 与 DrissionPage 的兼容

新版本不兼容旧版数据格式。`RESPONSE_DIR` 目录结构不变（每条 API 的 JSON 文件），但 `api_records` 改为纯事件驱动记录，不再有 `resourceType` 字段。

### E. 依赖

```
# pyproject.toml
dependencies = [
    "playwright>=1.48",
    "httpx>=0.27",
    "fastmcp>=2.0",
]
# 删除 DrissionPage
```

Playwright 首次需要 `playwright install chromium` 下载浏览器二进制。
