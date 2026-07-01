# 006: Content-Type 过滤 + 监听失效

> **来源**: ROADMAP.md 已知问题 #6（🔴 高优先级）
> **优先级**: P0（影响 API 捕获率，是 web-scout 核心能力）
> **影响范围**: `monitor.py` · `server.py`（#0 设计微调）

---

## 一、问题诊断

ROADMAP 将此问题分为两个子问题：

### 6a. Content-Type 过滤太窄

**现状** (`monitor.py:81-101`):

```python
def filter_and_store(self, packet) -> bool:
    content_type = resp_headers.get("content-type", "")
    if "application/json" not in content_type:
        return False  # ← 仅放行 application/json
```

**漏掉的场景**:

| 站点 | 实际 Content-Type | body 是 JSON？ | 当前结果 |
|------|-------------------|---------------|---------|
| 天天基金 `rankhandler.aspx` | `text/plain` | ✅ JSONP 包裹的 JSON | ❌ 被过滤 |
| 部分内地政府/金融 API | `application/octet-stream` | ✅ JSON | ❌ 被过滤 |
| 部分 legacy API | 无 Content-Type 头 | ✅ JSON | ❌ 被过滤 |

### 6b. 监听本身可能失效

ROADMAP 确认三重根因：

| 根因 | 机制 | 实例 |
|------|------|------|
| 6b.1 — 监听启动晚 | `listen.start()` 在 `tab.get(url)` 之后调用，页面同步请求已发完 | 天天基金 `APIs: 0` |
| 6b.2 — JSONP via `<script>` | 天天基金 `rankhandler.aspx` 通过 `<script>` 标签动态插入，不走 XHR/Fetch | 天天基金 Chrome DevTools 可见，web-scout 不可见 |
| 6b.3 — iframe 子帧 | 请求在 `<iframe>` 内发起 | 暂未确认但理论上可能 |

**CDP `Network.ResourceType` 完整枚举**（共 19 种）:

```
Document, Stylesheet, Image, Media, Font, Script, TextTrack,
XHR, Fetch, Prefetch, EventSource, WebSocket, Manifest,
SignedExchange, Ping, CSPViolationReport, Preflight, FedCM, Other
```

关键发现：**`Script` 是有效的 ResourceType**。JSONP 请求的资源类型是 `Script`，如果监听器只监听 XHR/Fetch，会漏掉。

---

## 二、修复设计

### 6a: Content-Type 放宽

**`monitor.py` `filter_and_store()` 修改**:

```python
def filter_and_store(self, packet) -> bool:
    if packet.is_failed:
        return False

    resp_headers = packet.response.headers
    content_type = resp_headers.get("content-type", "").lower()

    # 主方案: 标准 JSON Content-Type
    if "application/json" not in content_type:
        # 放宽方案: text/plain 或 application/octet-stream 或无 Content-Type
        body = packet.response.body
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                # 最后手段: 尝试 JSONP 格式 "callback({...})"
                body = self._try_parse_jsonp(body)
                if body is None:
                    return False
        elif isinstance(body, (dict, list)):
            pass  # already parsed by DrissionPage
        else:
            return False
    else:
        body = packet.response.body
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                return False
        elif not isinstance(body, dict):
            return False

    # 后续存储逻辑不变...
```

**新增 `_try_parse_jsonp()` 辅助方法**:

```python
@staticmethod
def _try_parse_jsonp(text: str) -> dict | None:
    """Try to extract JSON from JSONP callback wrapper like `callback({...})`.
    
    Returns the parsed dict, or None if not valid JSONP.
    """
    import re
    m = re.match(r'^[a-zA-Z_$][\w$]*\s*\((.+)\)\s*;?\s*$', text.strip())
    if m:
        try:
            inner = m.group(1)
            return json.loads(inner)
        except (json.JSONDecodeError, ValueError):
            pass
    return None
```

### 6b.1: 监听启动时机 — 在导航之前启动

**核心原则**: DrissionPage 官方文档强调 `listen.start()` 之前的数据包获取不到。因此必须**先启动监听，再导航到页面**。

这需要微调 #0 的设计：

**旧 #0 设计**:
```
scout_open → 导航 → 等 DOM → 提取文本 → 返回
scout_analyze → 启动监听 → 等 3s → 收集 API → 返回
```

**新 #0 修正**:
```
scout_open → 启动监听(res_type=all) → 导航 → 等 DOM → 提取文本 → 返回
scout_analyze → 等 3s → 收集 API → 扫描 DOM → 返回
```

**改动**: `scout_open` 在 `browser.open(url)` 之前启动 `NetworkMonitor`，但不收集结果。

**`server.py` `scout_open` 修改**（在 #0 基础上的微调）:

```python
def scout_open(url: str) -> str:
    global _browser, _monitor, _dom, _login, _exporter, _login_pending

    # 清理上一次的状态
    _monitor = None
    _dom = None
    _exporter = None

    if not _browser:
        _browser = BrowserSession()

    # ← 6b.1 修复: 在导航前启动监听
    _monitor = NetworkMonitor(_browser.tab)
    _monitor.start()  # listen.start(res_type=True) 捕获所有类型

    try:
        result = _browser.open(url)
    except Exception as e:
        return f"Failed to open page: {e}"

    # 登录墙检测...
    # 返回文本...
```

### 6b.2: JSONP via `<script>` — 使用 `res_type=True`

**`monitor.py` `start()` 方法修改**:

```python
def start(self):
    """Begin listening to all network requests (all resource types)."""
    self.tab.listen.start(res_type=True)  # True = 监听所有 ResourceType
```

当前调用 `self.tab.listen.start()` 无参数，DrissionPage 默认行为可能是只监听 XHR/Fetch。设置 `res_type=True` 后监听所有类型（包括 `Script`），JSONP 请求将被捕获。

**`filter_and_store()` 也需要在 Step 阶段正确接收 Script 类型的数据包**。

`DataPacket` 对象有 `resourceType` 属性，我们可以在 step 循环中添加日志：

```python
def step(self, timeout: float = 2.0) -> list:
    new_packets = []
    for batch in self.tab.listen.steps(timeout=timeout, gap=5):
        items = batch if isinstance(batch, list) else [batch]
        for packet in items:
            # 6b.2: 所有 resourceType 都进入 filter_and_store
            # filter_and_store 内部按 Content-Type + 可 JSON 解析判断
            if self.filter_and_store(packet):
                new_packets.append(packet)
    return new_packets
```

### 6b.3: iframe 子帧 — 被动捕获 + CDP 兜底

**现状分析**: DrissionPage `DataPacket` 有 `frameId` 属性。tab.listen 通常默认监听所有帧。但若某些场景下 iframe 请求被遗漏，使用 CDP 兜底。

**实现**: 在 `filter_and_store()` 中不对 `frameId` 做过滤 — 这意味着所有帧的请求都会进入。这本来就是当前代码的行为（没有 frameId 判断）。

**CDP 兜底方案**（仅在 listen 方案确实无法捕获时启用）:

```python
# monitor.py — 新增备用方法
def start_cdp_fallback(self):
    """Fallback: subscribe to ALL network events via CDP, bypassing DrissionPage listen."""
    self.tab.run_cdp('Network.enable')
    
    def _on_response_received(**kwargs):
        # kwargs 包含 requestId, type, response 等
        # 手动构建类似 DataPacket 的结构
        ...
    
    # CDP 事件通过 tab.set_settings 或 await 方式订阅
    # 复杂度高，作为 reserve option
```

**决策**: 6b.3 暂不实现完整 CDP 兜底，优先验证 `res_type=True` + `listen.start()` before navigation 的组合是否已经解决问题。若实测仍有 0 API 的场景，再启用 CDP 方案。

---

## 三、涉及的 #0 设计变更

| #0 设计点 | 原方案 | 修正 |
|-----------|--------|------|
| `scout_open` 是否启动监听 | 否 | **是** — 在导航前静默启动 `NetworkMonitor` |
| `scout_analyze` 是否启动监听 | 是 | **否** — 监听已由 `scout_open` 启动，仅做收集 |
| `NetworkMonitor.start()` | `tab.listen.start()` | `tab.listen.start(res_type=True)` |

---

## 四、测试要点

| 场景 | URL | 验证方式 |
|------|-----|---------|
| 标准 JSON API | B 站 `feed/rcmd` | `scout_analyze` → APIs > 0 |
| `text/plain` JSON | 天天基金 `rankhandler.aspx` | `scout_analyze` → APIs > 0，之前为 0 |
| JSONP callback | 任意 JSONP 接口 | `filter_and_store` 成功解析 `callback({...})` |
| `application/octet-stream` JSON | 部分金融/政府 API | APIs > 0 |
| `<script>` 动态插入 JSONP | 天天基金首页 | `res_type=True` 捕获到 Script 类型 |
| 登录页（监听无用） | 各种 /login | `scout_analyze` → `0 APIs captured`（不报错，正常） |
| SPA 首页 | B 站首页 | APIs > 0（之前可能为 0） |
| iframe 内请求 | 嵌入 iframe 的页面 | `frameId` 非空但正常存储 |

---

## 五、文件改动汇总

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/web_scout/monitor.py` | `filter_and_store()` 放宽 Content-Type 检查；新增 `_try_parse_jsonp()`；`start()` 改为 `res_type=True` | ~30 行 |
| `src/web_scout/server.py` | `scout_open` 在导航前启动 `NetworkMonitor`；`scout_analyze` 移除 `listen.start()` 调用 | ~5 行调整 |

---

## 六、DrissionPage / CDP API 速查

| 用途 | API | 来源 |
|------|-----|------|
| 启动监听（所有 ResourceType） | `tab.listen.start(res_type=True)` | listener docs |
| 遍历捕获的数据包 | `tab.listen.steps(timeout=..., gap=5)` | listener docs |
| 数据包资源类型 | `packet.resourceType` — `"Script"` / `"XHR"` / `"Fetch"` 等 | DataPacket 属性 |
| 数据包所属帧 | `packet.frameId` | DataPacket 属性 |
| CDP 兜底 | `tab.run_cdp('Network.enable')` | page_operation docs |
| CDP 资源类型枚举 | 19 种值（见上文） | CDP Network domain |
