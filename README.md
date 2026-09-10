# 斥候（veddata）

> **免责声明**: 本项目仅用于学习、研究和技术交流。使用者应遵守目标网站的 `robots.txt` 和服务条款，自行承担所有法律责任。项目作者不鼓励、不参与任何违反法律法规的使用行为。

帮助 AI 发现网页数据源的 MCP 服务器——不是爬虫，而是让 AI 知道"数据在哪、长什么样"的侦察工具。

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)

> [English README](./README_EN.md)

## 定位

**斥候 是一个发现工具，不是爬虫。**
**也不是通用浏览器**——浏览网页有其他 MCP 工具更合适，这里页面访问只是发现数据源的前置步骤。

| ✅ 做的 | ❌ 不做的 |
|---------|----------|
| 事件驱动捕获网络请求 + 内嵌数据 | 交互式断点调试（单步/暂停） |
| DOM 目录树：容器/字段/交互标记 | JS 加密 / wasm 逆向 |
| 请求参数 + 响应结构提取 | WebSocket 二进制帧解码 |
| 批量观测：请求/JS 断点自动拍照 | E2EE 解密 |
| 压缩字段文档 → AI 据此写爬虫 | 反检测 / 风控对抗 |

适用于标准 HTTP JSON API 站点。不适用于加密数据流、wasm 混淆等逆向场景。

## 原理

```
网站 → 浏览器（Playwright 事件驱动捕获）
       ↓                                ↓
  网络请求 + 内嵌数据               DOM 目录树
  （带触发时机，不贴类型标签）       （容器/字段/交互标记）
       ↓                                ↓
  ved_goto 返回数据源清单 ←────────────┘
       ↓
  关键词反查（ved_search / ved_trace_value）→ 字段路径
       ↓
  批量观测（ved_watch）→ 请求/JS 断点自动拍照 → 变量中间值
       ↓
  字段文档（ved_export）→ AI 据此写爬虫
```

## 快速开始

```bash
git clone https://github.com/SanZiNEO/veddata.git
cd veddata
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e .
```

### MCP 配置

**路径配置只有命令行参数这一条通路** —— `args` 是所有 MCP 客户端都有的公共面，而 `env` 的传递各家并不一致。两个参数都可选，但**要用导出/截图就必须给 `--response-dir`**：

| 参数 | 默认 | 说明 |
|------|------|------|
| `--profile-dir <绝对路径>` | `<用户数据根>/veddata/profile` | 浏览器 profile，保留登录态 |
| `--response-dir <绝对路径>` | **无**（不配置则写盘时报错） | 导出 / 截图落地目录 |

只接受**绝对路径**（`~` 会展开）；相对路径被拒绝 —— 相对路径要按 CWD 解析，而各家 harness 是否设 CWD、设成什么都不一样。

Claude Desktop / Cursor 这类 `mcpServers` 配置：

```json
{
  "mcpServers": {
    "veddata": {
      "command": "path\\to\\veddata\\.venv\\Scripts\\python.exe",
      "args": ["-m", "veddata.server", "--response-dir", "D:\\veddata-out"]
    }
  }
}
```

VS Code（`args` 支持 `${workspaceFolder}`，可以让产物跟着项目走）：

```json
{
  "servers": {
    "veddata": {
      "command": "path\\to\\veddata\\.venv\\Scripts\\python.exe",
      "args": ["-m", "veddata.server", "--response-dir", "${workspaceFolder}\\.veddata-out"]
    }
  }
}
```

运行期环境变量（只管浏览器行为，与路径无关）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HEADLESS` | `"false"` | 无头模式（`"true"` 不显示浏览器窗口） |
| `BROWSER_PATH` | 自动 | 浏览器路径，`"edge"` 使用 Edge |
| `BROWSER_ADDRESS` | 无 | 连接已有浏览器（如 `127.0.0.1:9222`），设置后忽略 HEADLESS/BROWSER_PATH |
| `MAX_TEXT_LENGTH` | `"3000"` | 页面文本最大字符数 |

### 路径与数据

不会写进你的项目目录，**也不依赖进程 CWD** —— 同一个客户端在任何 agent / harness 平台、任何工作目录下启动，落点都一样：

```
<用户数据根>/veddata/        Windows: %LOCALAPPDATA%\veddata
├── profile/                 浏览器 profile（默认，保留登录态）
└── cache/                   ved_fetch 的页面文本缓存（内部用，只保留最近 32 个）

<--response-dir>/            导出 / 截图等交付物，位置由你在配置里指定
```

- **默认一份 profile、跨会话保留登录态**，不随启动目录变化。
- 一个 Chromium profile 同一时刻只能被一个浏览器占用：**两个会话同时开浏览器会撞车**（第二个启动失败）。要并行就各自指定不同的 `--profile-dir`。
- **导出文件按站点名 + 时间戳命名**：`<站点名>_<接口名>_<YYYYMMDD-HHMMSS>.json`；截图是 `[<前缀>_]<站点名>_<YYYYMMDD-HHMMSS>.png`。站点名从 URL 简单解析：`www.example.com` → `example`，`api.example.co.uk` → `example`。同一秒重复导出才追加 `-2`。
- `--response-dir` 没配时，**只有 3 个写盘工具报错**（`ved_export` / `ved_export_all` / `ved_screenshot`），其余工具照常；错误信息里写明该怎么配。
- **程序不做任何自动清理**，交付物归你管。

### 输出上限与续读

单次工具结果有**软上限**，超了就截断，并且**一定告诉你下一步怎么取**（对齐 opencode / 官方 fetch server / DSH 的通行做法）：

| 约定 | 值 | 说明 |
|------|-----|------|
| 单次结果软上限 | ~8000 字符 | 超了截断，页脚给出续读参数 |
| 单行上限 | 2000 字符 | 压缩成一行 1 MB 的 JS bundle 靠它兜住 |
| 列表默认条数 | 30（`limit=` 可调） | 页脚给出 `offset=N` |
| 树默认深度 | 2（`depth=` 可调） | `ved_goto` / `ved_dom_tree` / `ved_dom_locate` |
| 内联数据 | 只给摘要 | `data:` URI 里 200 KB+ 的 wasm/base64 不会整段返回 |

**三种分页粒度，不要混**：

- 行号 —— `ved_script_source(start_line=, line_count=)`，或直接用 `query=` 定位
- 字符 offset —— `ved_fetch(max_length=, start_index=)`
- 条数 offset —— `ved_apis` / `ved_dom_search` / `ved_list_scripts` / `ved_scan` 的 `offset` / `limit`

被截断的**全量**会在配了 `--response-dir` 时顺手写到 `<response-dir>/_spill/`（只保留最近 32 份），返回里给出路径；没配就只给分页参数（不报错）。信息本身都留在服务端，随时可以再取。

## 工具（29 个）

### 导航（6 个）
| 工具 | 说明 |
|------|------|
| `ved_open` | 启动数据发现会话，打开浏览器开始捕获页面数据源。不导航 |
| `ved_goto` | 导航到目标页面，自动发现所有数据来源：返回 DOM 树 + 数据源清单 + 操作列表 |
| `ved_close` | 关闭整个浏览器，清空所有数据 |
| `ved_tabs` | 列出所有标签页，标注当前活跃 |
| `ved_tab_switch` | 切换到指定标签页（短 ID 前缀匹配） |
| `ved_tab_close` | 关闭指定标签页，清理其数据记录。支持逗号分隔批量关闭 |

### 观察（7 个）
| 工具 | 说明 |
|------|------|
| `ved_fetch` | 获取页面全文（滚动到底 + innerText + 链接），辅助定位数据关键词 |
| `ved_screenshot` | 截取当前页面（可视区域或整页） |
| `ved_dom_tree` | 输出 DOM 目录树（内存快照）：容器/字段/交互标记，导航后自动重扫 |
| `ved_dom_search` | 在内存 DOM 树中搜文本/属性/id，返回节点路径 |
| `ved_dom_locate` | 按路径定位节点（如 `div.content > div.post-list > article:nth-child(3)`） |
| `ved_cookies` | 查看 cookie（当前域或全部，摘要或完整信息）。指定 tab 获取对应标签页 |
| `ved_console` | 操作页面控制台：执行 JS / 查看 log/warn/error 消息 |

### 交互（2 个）
| 工具 | 说明 |
|------|------|
| `ved_act` | 链式操作（input/scroll/click/select），每步报告新增数据记录 + 触发上下文 |
| `ved_login` | 等待用户在浏览器中手动登录，通过 cookie 变化检测 |

### 发现（13 个）
| 工具 | 说明 |
|------|------|
| `ved_apis` | 列出已捕获的所有数据（网络请求、内嵌数据、JS 变量），每条带触发时机，不贴类型标签 |
| `ved_inspect` | 查看数据的完整请求/响应，支持逗号分隔多 ID |
| `ved_search` | 跨数据源搜索：网络 → 内嵌 → 脚本源码 → DOM，支持逗号分隔多关键词 |
| `ved_context` | 搜索关键词返回精确字段路径 + 采样值，支持逗号分隔多关键词 |
| `ved_watch` | 批量观测：注册请求/JS 断点观测点 → 触发 → 一次取回全部变量快照（自动继续，不打断页面） |
| `ved_list_scripts` | 列出页面所有 JS 脚本的 URL、大小和行数 |
| `ved_search_scripts` | 全局搜索所有 JS 源码（支持 /regex/） |
| `ved_script_source` | 查看单个脚本源码，支持搜索高亮和上下文 |
| `ved_trace_value` | 值追踪：一个值在 JS 源码/网络/DOM/变量/WS 中流经的所有位置 |
| `ved_export` | 导出数据：字段文档 + 原始 JSON，支持逗号分隔多 ID |
| `ved_export_all` | 批量导出所有已捕获的数据 |
| `ved_peek` | 打开页面 → 自动捕获 → 按路径匹配数据 → 一步返回详情 |
| `ved_request` | 重放 HTTP 请求（复用捕获参数或自定义），自动同步浏览器 cookie |

### 扫描（1 个）
| 工具 | 说明 |
|------|------|
| `ved_scan` | `mode="all"` 全量扫描（API + DOM 树 + 内嵌数据）。`mode="dom"` 关键词扫描 |

## 推荐工作流

### 🚀 快速路径（推荐）

从页面数据清单里选一个关键词，直接反查数据来源：

1. `ved_open()` → `ved_goto(url)` — 启动浏览器 → 导航，读 DOM 树 + 数据源清单，选关键词
2. `ved_act("scroll")` — 滚动加载，触发推荐/动态流等接口
3. `ved_search("词1,词2")` — 用关键词反查，看哪些数据源里有它们
4. `ved_context("词1,词2")` — 看精确字段路径和值，确认目标
5. `ved_inspect(indices="1,3")` → `ved_export(indices="1,3")` — 批量查看和导出

**核心思路**：跳过枚举（scan/apis），从关键词直接反推 API 和字段路径。比全量扫描快。

### 全量扫描（不知道关键词时）

完全没有方向时，先看页面有哪些数据源：

1. `ved_open()` → `ved_goto(url)` — 直接看 DOM 树和数据清单
2. `ved_scan(mode="all")` — 一次性抓 API + DOM 结构 + 内嵌数据
3. `ved_apis()` — 列出所有端点，逐个 `ved_inspect(n)`

### 批量观测（逆向定位）

想在代码执行到某处时拿到当时的中间值（如加密参数）：

1. `ved_search_scripts("encrypt")` — 定位敏感代码行
2. `ved_watch(observations=[{"type":"js","url":"...app.js","line":147,"variables":["key"]}])` — 注册断点观测
3. `ved_act(...)` — 触发操作，断点命中自动拍照并继续（页面不停）
4. `ved_watch(collect=True)` — 一次取回全部变量快照

### 数据全在 HTML 里的页面

没有 XHR 请求时 `ved_apis()` 数量少是正常的。用 `ved_dom_search` + `ved_trace_value` 找内嵌数据（`<script>` JSON 块、`window.__xxx__` 全局变量）。

## 架构

```
src/veddata/
├── server.py           # FastMCP 入口 + 29 个工具
├── state.py            # 全局状态 + attach_page 统一挂接（monitor/脚本注册表）
├── browser.py          # Playwright 封装 + 多标签页自动注册 + 前缀匹配
├── network_monitor.py  # 事件驱动数据捕获（网络/内嵌/WS）+ 触发上下文，无类型标签
├── dom.py              # DOM 目录树：内存快照 + 折叠 + 搜索/定位
├── watch_engine.py     # 批量观测：请求观测 + JS 断点自动拍照放行
├── scripts.py          # JS 脚本收集（scriptParsed）/ 搜索 / 源码
├── requester.py        # httpx 请求执行器 + cookie 同步
├── export.py           # 压缩字段文档 + 原始数据包保存
├── login.py            # cookie 变化检测登录 + 手动登录等待
└── tools/
    ├── navigate.py     # 导航: open goto close tabs tab_switch tab_close
    ├── observe.py      # 观察: fetch screenshot dom_tree dom_search dom_locate cookies console
    ├── act.py          # 交互: act login
    ├── discover.py     # 发现: apis inspect search context watch scripts trace export peek request
    └── scan.py         # 扫描: scan
```

## License

MIT © [ShanZhi](https://github.com/SanZiNEO)

---

> **免责声明**
> 
> 本项目（斥候）是一个通用的网页数据源发现工具，本身不发起爬取请求，不存储、不传输任何网站数据。使用者应：
> 
> 1. 遵守目标网站的 `robots.txt` 和服务条款（Terms of Service）
> 2. 控制请求频率，不对目标网站造成异常负载
> 3. 仅抓取公开数据，不绕过网站的认证和授权机制
> 4. 自行承担使用本工具所产生的全部法律责任
> 
> 项目作者（ShanZhi / SanZiNEO）不鼓励、不参与任何违反法律法规或网站条款的使用行为。本工具仅用于学习、研究和技术交流目的。

---

**声明：** 本项目由 AI 辅助开发，目标是帮助 AI 和开发者快速发现网页数据源，不包含任何破解、绕过或恶意功能。用户应遵守目标网站的 `robots.txt` 及相关法律法规。
