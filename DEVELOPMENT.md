# Web Scout — 开发计划

## 定位

**Web Scout 是一个网页数据源发现工具，不是爬虫。**

| ✅ 做的 | ❌ 不做的 |
|---------|----------|
| Network 面板 → JSON API 数据包 | XHR 断点追踪调用链 |
| DOM → 重复结构 + 字段路径 | JS 加密逻辑逆向 |
| 请求参数 + 响应结构提取 | WebSocket 帧解码 |
| 页面文本提取 | E2EE 解密 |
| 输出字段文档给 AI 写爬虫 | 自动生成可运行的爬虫代码 |

适合：数据走标准 HTTP API 的站点（小红书/B站/电商等），AI 拿到字段文档后直接写爬虫。

不适合：加密数据流、wasm 混淆、WebSocket 二进制帧、需要断点调试才能看清的逆向场景。那是逆向工程，不是发现。

---

## 目标

MCP server，帮 AI（和人类）快速发现网页的数据源。

- AI 调用 MCP 打开页面 → 拿到全文 Markdown
- AI 看文本选关键词 → MCP 搜索 → 定位数据源
- 数据源分两类：**API 数据包**（请求参数 + 响应结构）和 **DOM 元素**（选择器路径 + 字段列表）
- 一个 session 内可多次操作，同时捕获多个数据源（如同时拿到评论 + 子评论）

---

## 四种获取路径

### 路径 1 — 文本提取（`text`）

打开页面 → 去掉导航/页脚/广告 → 转 Markdown → 返回给 AI。
AI 阅读文本后自行选择关键词。

毫秒级，不需要解析 DOM 结构。是所有后续操作的前置步骤。

适合：任何页面。

### 路径 2 — 数据包优先（默认 `auto`）

`text` 获取关键词 → 搜索 → 捕获匹配关键词的 API 数据包。
API 无命中则回退 DOM。

适合：不明确数据在哪的通用场景。

### 路径 3 — 仅数据包（`api`）

`text` 获取关键词 → AI 选词搜索 → 只看 API。

适合：已知数据走 API 的 SPA 站点（小红书、B站）。

### 路径 4 — 仅元素（`dom`）

两种子模式：
- **文本搜索**：在 DOM 中搜索包含关键词的元素
- **相似合并**：找重复容器（≥3 个相同 tag+class 的兄弟元素），自动提取字段

适合：静态页面、电商列表。

---

## 完整工作流

```
用户: "爬小红书评论"

AI: scout_open(url, mode="api")
→ 全文 Markdown: "搜索发现: 减脂餐 健身计划 周末去哪儿 OOTD..."

AI: scout_action("search", "减脂餐")
→ 新增 2 个 API

AI: scout_action("click", 5)              ← 点击搜索结果中的笔记
→ 新增 3 个 API（评论 + 子评论 + 用户信息）

AI: scout_list_apis()
→ [1] POST /api/search/notes       2 次 → 20 fields
   [2] GET  /api/comment/page       1 次 → 15 fields  ← 评论
   [3] GET  /api/comment/sub/page   1 次 → 12 fields  ← 子评论

AI: scout_export(2)  → 评论字段文档 + 原始数据包
AI: scout_export(3)  → 子评论字段文档 + 原始数据包
```

同一 session 多操作多捕获，AI 逐个 inspect/export。

---

## 工具清单

### `scout_open`

```
打开目标 URL，启动浏览器 → 提取全文 Markdown → 开始监听网络请求。

参数:
  url:  str           — 目标网页地址
  mode: str = "auto"  — "auto" | "api" | "dom" | "text"

自动检测登录墙 → 提示 AI 调用 scout_wait_login

返回:
  - 页面标题
  - 全文 Markdown（去导航/页脚/脚本）
  - 页面加载时触发的 API 数量
  - 下一步建议
```

### `scout_action`

```
在页面上执行操作，触发新 API 被捕获。

参数:
  action: str       — "search" | "scroll"
  value: str = None — 搜索关键词

返回:
  - 操作状态
  - 新增 API 数量
```

### `scout_wait_login`

```
等待用户在浏览器中手动登录。检测到登录成功 → 自动刷新 → 继续。

参数:
  timeout: int = 300 — 最大等待秒数

检测逻辑:
  - URL 离开 /login → 判定成功
  - 验证弹窗出现 → 等待手动完成（.nc_wrapper / text=安全验证）
  - sleep(3) 等 cookie 落盘 → 刷新页面 → 重新监听
```

### `scout_list_apis`

```
列出当前 session 捕获的所有 JSON API。

返回:
  [1] POST /api/search/notes       2 次 → 20 fields
  [2] GET  /api/comment/page       1 次 → 15 fields
  [3] GET  /api/comment/sub/page   1 次 → 12 fields
```

### `scout_inspect_api`

```
查看某个 API 的完整请求和响应。

返回:
  === 请求 ===
  URL:     https://edith.xiaohongshu.com/api/comment/page
  Method:  GET
  Headers: Content-Type, x-s, x-t, Referer, Cookie: a1=...; web_session=...
  Params:  note_id=xxx, cursor=, page_size=20

  === 响应 ===
  Status: 200
  Body (前 2000 字符):
    {"code": 0, "data": {"comments": [{"id": "...", ...
```

### `scout_list_elements`

```
列出页面上可交互的元素，AI 自主选择下一步。

返回:
  [1] a       "减脂餐"       → href=/search_result/...
  [2] button  "视频"         → class=.tab-btn
  [3] button  "图文"         → class=.tab-btn
  [4] .product-card[]        共 20 条 → title price sales img
```

### `scout_click`

```
点击指定元素，触发新 API。

参数:
  index: int — 元素编号
```

### `scout_export`

```
导出数据源。API 模式返回请求参数+响应结构，DOM 模式返回选择器路径+字段表。

参数:
  index: int              — 编号
  format: str = "both"    — "raw" | "compact" | "both"

输出:
  1. 原始数据包（保存到 response/ 目录）
  2. 压缩版字段文档
```

---

## 响应结构（DOM 模式）

```
DOM .product-card[]: 本次=20

[0] 结构:
  .title    : text = "法式复古连衣裙"
  .price    : text = "¥199"
  .sales    : text = "已售 1200"
  .img      : img  = "https://..."
  .link     : href = "/product/12345"

[1+] 差异:
  | # | .title        | .price | .sales      |
  |---|---------------|--------|-------------|
  | 1 | "韩系连衣裙"   | "¥259" | "已售 850"  |
```

## 响应结构（API 模式）

```
code: 0, msg: "成功"

data.comments[]: 本次=10

[0] 结构:
  id                : string = "69e371f9..."
  content           : string = "在哪儿呢"
  like_count        : string = "44"
  ip_location       : string = "江苏"
  user_info.user_id : string = "633b0499..."
  sub_comments[]:        ← 嵌套数组同样展开
    id          : string = "69e374db..."
    content     : string = "南京溧水"

分页参数: page_size=20, has_more=true
→ 已保存: response/comment_page.json
```

---

## 压缩算法（API 响应）

| 规则 | 说明 |
|------|------|
| R1 顶层分离 | `code: 0, msg: "成功"` |
| R2 data 内联 | `has_more: true, user_id: "xxx"` |
| R3 数组 [0]+差异表 | 第一项完整结构，后续只列不同字段 |
| R4 嵌套同样展开 | `sub_comments[]` 同上规则 |
| R5 计数标注 | `本次=10 / 总计=33`, `page_size=20` |
| R6 类型推断 | int/float/bool/string/list |
| R7 长值截断 | URL>46 / content>20 字符截断 |

预估：12KB JSON → 800 字符，15x 压缩。

---

## 决策点

| 工具 | 返回 | AI 决定 |
|------|------|--------|
| `scout_open`（登录墙） | "需登录" | → `scout_wait_login` |
| `scout_open`（正常） | 全文 Markdown | 选关键词 → `scout_action("search")` |
| `scout_action("search")` | 新增 API 数 | 继续搜？→ `scout_list_apis`？ |
| `scout_list_apis` | 编号列表 | 选哪个 inspect/export？ |
| `scout_list_elements` | 元素列表 | 选哪个 click？选哪个容器？ |
| `scout_inspect_api` | 请求+响应 | 确认？export？换一个？ |

---

## 架构

```
src/web_scout/
├── server.py      # FastMCP 入口 + 8 个工具 + 会话状态
├── browser.py     # Chromium 封装（启动/关闭 + 登录检测 + 页面文本提取）
├── monitor.py     # 网络监听 + API 过滤 + 存储
├── dom.py         # 元素扫描 + 点击交互 + 容器合并
└── export.py      # 压缩算法 + 原始数据包保存
```

## 技术栈

| 库 | 版本 | 用途 |
|------|------|------|
| `DrissionPage` | `>=4.1` | 浏览器全部工作 |
| `fastmcp` | `>=2.0` | MCP 框架 |

只用两个库。`requests` / `playwright` / `curl_cffi` 不需要。

### 浏览器 API

使用 4.2 新写法（4.1 兼容）：

```python
from DrissionPage import Chromium, ChromiumOptions

co = ChromiumOptions()
co.auto_port(True)  # 自动分配端口

browser = Chromium(co)
tab = browser.latest_tab
tab.get(url)
tab.listen.start()
```

### 环境变量（全部可选）

| 变量 | 默认值 | 作用 |
|------|--------|------|
| `HEADLESS` | `"false"` | 无头模式 |
| `BROWSER_PATH` | 空 | 浏览器路径，`"edge"` 用 Edge |
| `RESPONSE_DIR` | `"./response"` | 数据包保存目录 |
| `LOGIN_TIMEOUT` | `"300"` | 登录等待秒数 |
| `USER_DATA_DIR` | 空 | 持久化用户文件夹 |
| `AUTO_CLOSE` | `"true"` | 导出后自动关浏览器 |

---

## 不做的

- 登录/认证自动化
- 风控规则推断
- 字段依赖关系推断
- 多页面并行

---

## 实现顺序

1. `browser.py` — 浏览器启动 + 页面文本提取 + 登录检测
2. `monitor.py` — 网络监听 + API 过滤 + 存储
3. `dom.py` — 元素扫描 + 容器合并 + 字段提取
4. `server.py` — FastMCP 8 个工具 + 会话管理
5. `export.py` — 压缩算法 + 原始数据包保存
6. 联调 — 小红书 + B站实测
