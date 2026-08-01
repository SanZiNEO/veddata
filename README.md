# Web Scout

> **免责声明**: 本项目仅用于学习、研究和技术交流。使用者应遵守目标网站的 `robots.txt` 和服务条款，自行承担所有法律责任。项目作者不鼓励、不参与任何违反法律法规的使用行为。

帮助 AI 发现网页数据源的 MCP 服务器——不是爬虫，而是让 AI 知道"数据在哪、长什么样"的侦察工具。

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)

> [English README](./README_EN.md)

## 定位

**Web Scout 是一个发现工具，不是爬虫。**
**也不是通用浏览器**——浏览网页有其他 MCP 工具更合适，这里页面访问只是发现数据源的前置步骤。

| ✅ 做的 | ❌ 不做的 |
|---------|----------|
| Network 面板 → JSON API 端点 | XHR 断点追踪调用链 |
| DOM → 重复结构 + CSS 选择器 | JS 加密 / wasm 逆向 |
| 请求参数 + 响应结构提取 | WebSocket 二进制帧解码 |
| 页面全文 → Markdown 给 AI 阅读 | E2EE 解密 |
| 压缩字段文档 → AI 据此写爬虫 | 自动生成可运行的爬虫代码 |

适用于标准 HTTP JSON API 站点。不适用于加密数据流、wasm 混淆等逆向场景。

## 原理

```
网站 → 浏览器 → 全文 Markdown
       ↓           ↓
  网络监听     AI 阅读文本 → 选关键词
       ↓           ↓
  API 捕获     搜索 → 匹配含关键词的 API
       ↓               ↓
  字段文档 ←──────────┘
  原始数据包保存到本地
```

## 快速开始

```bash
git clone https://github.com/SanZiNEO/web-scout.git
cd web-scout
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e .
```

### MCP 配置

在 `kilo.json` 中添加：

```json
"web-scout": {
    "type": "local",
    "command": ["path\\to\\web-scout\\.venv\\Scripts\\web-scout.exe"],
    "enabled": true
}
```

可选环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HEADLESS` | `"false"` | 无头模式（`"true"` 不显示浏览器窗口） |
| `BROWSER_PATH` | 自动 | 浏览器路径，`"edge"` 使用 Edge |
| `BROWSER_ADDRESS` | 无 | 连接已有浏览器（如 `127.0.0.1:9222`），设置后忽略 HEADLESS/BROWSER_PATH |
| `MULTI_BROWSER` | `"false"` | `"true"` 时尝试多个调试端口（9222-9231），避免端口冲突 |
| `USER_DATA_DIR` | 临时 | 持久化用户文件夹，保留登录态 |
| `LOGIN_TIMEOUT` | `"300"` | 登录最大等待秒数 |
| `MAX_TEXT_LENGTH` | `"3000"` | scout_open 页面文本最大字符数 |
| `RESPONSE_DIR` | `"./response"` | 数据导出默认目录，可用 `output_dir` 参数覆盖 |
## 工具（29 个）

### 导航（6 个）
| 工具 | 说明 |
|------|------|
| `scout_open` | 启动数据发现会话，打开浏览器开始捕获页面数据源。不导航 |
| `scout_goto` | 导航到目标页面，自动发现所有数据来源：返回 DOM 树 + 数据源清单 + 操作列表 |
| `scout_close` | 关闭整个浏览器，清空所有数据 |
| `scout_tabs` | 列出所有标签页，标注当前活跃 |
| `scout_tab_switch` | 切换到指定标签页（短 ID 前缀匹配） |
| `scout_tab_close` | 关闭指定标签页，清理其数据记录。支持逗号分隔批量关闭 |

### 观察（7 个）
| 工具 | 说明 |
|------|------|
| `scout_fetch` | 获取页面全文（滚动到底 + innerText + 链接），辅助定位数据关键词 |
| `scout_screenshot` | 截取当前页面（可视区域或整页） |
| `scout_dom_tree` | 输出 DOM 目录树（内存快照）：容器/字段/交互标记，导航后自动重扫 |
| `scout_dom_search` | 在内存 DOM 树中搜文本/属性/id，返回节点路径 |
| `scout_dom_locate` | 按路径定位节点（如 `div.content > div.post-list > article:nth-child(3)`） |
| `scout_cookies` | 查看 cookie（当前域或全部，摘要或完整信息）。指定 tab 获取对应标签页 |
| `scout_console` | 操作页面控制台：执行 JS / 查看 log/warn/error 消息 |

### 交互（2 个）
| 工具 | 说明 |
|------|------|
| `scout_act` | 链式操作（input/scroll/click/select），每步报告新增数据记录 + 触发上下文 |
| `scout_login` | 等待用户在浏览器中手动登录，通过 cookie 变化检测 |

### 发现（13 个）
| 工具 | 说明 |
|------|------|
| `scout_apis` | 列出已捕获的所有数据（网络请求、内嵌数据、JS 变量），每条带触发时机，不贴类型标签 |
| `scout_inspect` | 查看数据的完整请求/响应，支持逗号分隔多 ID |
| `scout_search` | 跨数据源搜索：网络 → 内嵌 → 脚本源码 → DOM，支持逗号分隔多关键词 |
| `scout_context` | 搜索关键词返回精确字段路径 + 采样值，支持逗号分隔多关键词 |
| `scout_watch` | 批量观测：注册请求/JS 断点观测点 → 触发 → 一次取回全部变量快照 |
| `scout_list_scripts` | 列出页面所有 JS 脚本的 URL、大小和行数 |
| `scout_search_scripts` | 全局搜索所有 JS 源码（支持 /regex/） |
| `scout_script_source` | 查看单个脚本源码，支持搜索高亮和上下文 |
| `scout_trace_value` | 值追踪：一个值在 JS 源码/网络/DOM/变量/WS 中流经的所有位置 |
| `scout_export` | 导出数据：字段文档 + 原始 JSON，支持逗号分隔多 ID |
| `scout_export_all` | 批量导出所有已捕获的数据 |
| `scout_peek` | 打开页面 → 自动捕获 → 按路径匹配数据 → 一步返回详情 |
| `scout_request` | 重放 HTTP 请求（复用捕获参数或自定义），自动同步浏览器 cookie |

### 扫描（1 个）
| 工具 | 说明 |
|------|------|
| `scout_scan` | `mode="all"` 全量扫描（API + DOM 树 + 内嵌数据）。`mode="dom"` 关键词扫描 |

## 推荐工作流

### 🚀 快速路径（推荐）

从页面文本中选一个关键词，直接反查数据来源：

1. `scout_open()` → `scout_goto(url)` — 启动浏览器 → 导航到页面，浏览渲染文本，选关键词（可多个）
2. `scout_act("scroll")` — 滚动加载，触发推荐/动态流等接口
3. `scout_search("词1,词2")` — 用关键词反查，看哪些 API 的响应体里有它们
4. `scout_context("词1,词2")` — 看精确字段路径和值，确认目标
5. `scout_inspect(indices="1,3")` → `scout_export(indices="1,3")` — 批量查看和导出

**核心思路**：跳过枚举（scan/apis），从关键词直接反推 API 和字段路径。四步定位，比全量扫描快。

### 全量扫描（不知道关键词时）

完全没有方向时，先看页面有哪些数据源：

1. `scout_open()` → `scout_goto(url)` → `scout_act("search", kw)` — 触发搜索接口
2. `scout_scan(mode="all")` — 一次性抓 API + DOM 容器 + SSR 数据
3. `scout_apis()` — 列出所有端点，逐个 `scout_inspect(n)`

### SSR 页面

数据全在 HTML 里，没有 XHR 请求。`scout_apis()` 返回 0 是正常的，改用 `scout_search` + `scout_scan(mode="dom")`。

## 架构

```
src/web_scout/
├── server.py           # FastMCP 入口 + 21 个工具
├── state.py            # 全局状态 + _api_pool + _dom_scanners
├── browser.py          # Chromium 封装 + CDP tab_id 管理 + 前缀匹配
├── network_pool.py     # API 公共池 + 按 tab_id 过滤 + 字段压缩
├── requester.py        # SessionPage 请求执行器 + cookie 同步
├── dom.py              # 元素扫描 + 容器发现 v3 + Common Actions
├── export.py           # 压缩字段文档 + 原始数据包保存
├── login.py            # cookie 变化检测登录 + 手动登录等待
└── tools/
    ├── navigate.py     # 导航: open goto close tabs tab_switch tab_close
    ├── observe.py      # 观察: fetch screenshot elements cookies
    ├── act.py          # 交互: act login
    ├── discover.py     # 发现: apis inspect search context export export_all peek request
    └── scan.py         # 扫描: scan
```

## License

MIT © [ShanZhi](https://github.com/SanZiNEO)

---

> **免责声明**
> 
> 本项目（Web Scout）是一个通用的网页数据源发现工具，本身不发起爬取请求，不存储、不传输任何网站数据。使用者应：
> 
> 1. 遵守目标网站的 `robots.txt` 和服务条款（Terms of Service）
> 2. 控制请求频率，不对目标网站造成异常负载
> 3. 仅抓取公开数据，不绕过网站的认证和授权机制
> 4. 自行承担使用本工具所产生的全部法律责任
> 
> 项目作者（ShanZhi / SanZiNEO）不鼓励、不参与任何违反法律法规或网站条款的使用行为。本工具仅用于学习、研究和技术交流目的。

---

**声明：** 本项目由 AI 辅助开发，目标是帮助 AI 和开发者快速发现网页数据源，不包含任何破解、绕过或恶意功能。用户应遵守目标网站的 `robots.txt` 及相关法律法规。
