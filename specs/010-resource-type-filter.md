# 010: 请求类型过滤 — 按 resourceType 跳过图片/CSS/字体

> **来源**: ROADMAP.md 已知问题 #10（🔴 B站实测）
> **优先级**: P0（图片/CSS/字体淹没 API 列表，干扰严重）
> **影响范围**: `monitor.py` — `filter_and_store()`

---

## 一、问题诊断

**现状** (`monitor.py:81-101`): `filter_and_store()` 只按 `is_failed` + `Content-Type` 过滤，不做 `resourceType` 过滤。

**B站实测**: 首页 33 个请求，`list_apis` 列出全部。其中 `#10-#26` 全是 Banner 图片、CSS、SVG 图标，真正的数据 API（`feed/rcmd`）被淹没。

**CDP ResourceType 完整枚举**（19 种）:

```
Document, Stylesheet, Image, Media, Font, Script, TextTrack,
XHR, Fetch, Prefetch, EventSource, WebSocket, Manifest,
SignedExchange, Ping, CSPViolationReport, Preflight, FedCM, Other
```

**应过滤的类型**:

| 类型 | 说明 | 原因 |
|------|------|------|
| `Image` | 图片 | Banner/图标，响应体是二进制 |
| `Stylesheet` | CSS | 样式文件 |
| `Font` | 字体 | woff/ttf |
| `Media` | 音视频 | mp4/mp3 |
| `Manifest` | PWA manifest | 无关 |
| `Prefetch` | 预加载 | 非实际数据 |
| `Ping` | 信标请求 | 无数据 |
| `CSPViolationReport` | CSP 报告 | 无数据 |
| `SignedExchange` | SXG | 罕见 |
| `Other` | 其他 | 未知类型保守跳过 |

---

## 二、目标设计

在 `filter_and_store()` 入口处增加 `resourceType` 白名单过滤：

```python
def filter_and_store(self, packet) -> bool:
    # 1. 失败检查
    if packet.is_failed:
        return False

    # 2. 资源类型过滤（新增）
    allowed_types = {"XHR", "Fetch", "Script", "Document", "EventSource"}
    resource_type = getattr(packet, 'resourceType', 'Other')
    if resource_type not in allowed_types:
        return False

    # 3. 后续的 Content-Type + JSON 解析逻辑不变...
```

### 白名单说明

| 资源类型 | 为什么保留 |
|---------|-----------|
| `XHR` | XMLHttpRequest — 最常见的 API 请求类型 |
| `Fetch` | Fetch API — 现代 SPA 的主流请求方式 |
| `Script` | JS 脚本 — JSONP 请求（#6b 修复后） |
| `Document` | 文档 — SSR 内嵌 JSON 在 `__INITIAL_STATE__` 场景（#7 修复后） |
| `EventSource` | SSE — 部分实时数据推送走 SSE |

---

## 三、实现细节

### 3.1 `monitor.py` — `filter_and_store()` 修改

```python
# 资源类型白名单（类常量）
ALLOWED_RESOURCE_TYPES = frozenset({"XHR", "Fetch", "Script", "Document", "EventSource"})

def filter_and_store(self, packet) -> bool:
    if packet.is_failed:
        return False

    # 资源类型过滤
    resource_type = getattr(packet, 'resourceType', 'Other')
    if resource_type not in ALLOWED_RESOURCE_TYPES:
        return False

    # 以下保持不变: Content-Type 检查 + JSON 解析 + 存储
    resp_headers = packet.response.headers
    content_type = resp_headers.get("content-type", "")
    ...
```

### 3.2 为何用白名单而不是黑名单

- CDP 可能在未来增加新的 `ResourceType` 值
- 白名单: 新类型默认不进来，手动评估后再加 → 安全
- 黑名单: 新类型默认进来，可能产生噪音 → 不安全

### 3.3 `WebSocket` 不在此修复中

WebSocket 数据的拦截由 DrissionPage 的 `include_ws()` 方法管理（ROADMAP "资源类型标注" 阶段处理）。`EventSource`（SSE）与 `WebSocket` 不同：SSE 走 HTTP，`DataPacket` 中 `resourceType=EventSource`。

---

## 四、测试要点

| 场景 | URL | 预期 |
|------|-----|------|
| B站首页 | `bilibili.com` | `list_apis` 只显示 XHR/Fetch，不显示图片/CSS |
| SPA 页面 | 知乎 | `resourceType=Fetch` 的 API 正常捕获 |
| JSONP 脚本 | 天天基金 | `resourceType=Script` 正常捕获 |
| 图片站（纯图） | 图片集页面 | `APIs: 0`（图片全被过滤） |
| 样式/CSS | 任意页面 | CSS 请求不出现 |

---

## 五、文件改动汇总

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/web_scout/monitor.py` | `filter_and_store()` 入口增加 `resourceType` 白名单过滤（~5 行）；新增类常量 `ALLOWED_RESOURCE_TYPES` | ~6 行 |
