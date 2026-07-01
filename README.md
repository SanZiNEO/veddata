# Web Scout

> **免责声明**: 本项目仅用于学习、研究和技术交流。使用者应遵守目标网站的 `robots.txt` 和服务条款，自行承担所有法律责任。项目作者不鼓励、不参与任何违反法律法规的使用行为。

帮助 AI 发现网页数据源的 MCP 服务器——不是爬虫，而是让 AI 知道"数据在哪、长什么样"的侦察工具。

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)

> [English README](./README_EN.md)

## 定位

**Web Scout 是一个发现工具，不是爬虫。**

| ✅ 做的 | ❌ 不做的 |
|---------|----------|
| Network 面板 → JSON API 端点 | XHR 断点追踪调用链 |
| DOM → 重复结构 + CSS 选择器 | JS 加密 / wasm 逆向 |
| 请求参数 + 响应结构提取 | WebSocket 二进制帧解码 |
| 页面全文 → Markdown 给 AI 阅读 | E2EE 解密 |
| 压缩字段文档 → AI 据此写爬虫 | 自动生成可运行的爬虫代码 |

适用于标准 HTTP JSON API 站点（小红书 / B站 / 电商）。不适用于加密数据流、wasm 混淆等逆向场景。

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
| `RESPONSE_DIR` | `"./response"` | 数据导出目录 |

## 工具（19 个）

### 导航（5 个）
| 工具 | 说明 |
|------|------|
| `scout_open` | 打开页面 → 提取渲染文本 → 开始监听网络 |
| `scout_close` | 关闭整个浏览器，清空所有数据 |
| `scout_tabs` | 列出所有标签页，标注当前活跃 |
| `scout_tab_switch` | 切换到指定标签页 |
| `scout_tab_close` | 关闭指定标签页，清理其监控数据 |

### 观察（3 个）
| 工具 | 说明 |
|------|------|
| `scout_fetch` | 获取当前页面完整文本 + 所有链接列表（支持分块读取） |
| `scout_screenshot` | 截取当前页面（可视区域或整页） |
| `scout_elements` | 列出可交互元素和 DOM 容器 |

### 交互（3 个）
| 工具 | 说明 |
|------|------|
| `scout_act` | 在页面执行搜索或滚动，触发新的 API 请求 |
| `scout_click` | 点击指定元素（翻页/切换 tab/加载更多） |
| `scout_login` | 等待用户在浏览器中手动登录 |

### 发现（7 个）
| 工具 | 说明 |
|------|------|
| `scout_apis` | 列出所有捕获的 API 端点，支持关键词过滤 |
| `scout_inspect` | 查看 API 的完整请求/响应（支持预览和完整模式） |
| `scout_search` | 全局搜索：API 响应体 → SSR JSON → 页面源码 → DOM 文本 |
| `scout_context` | 搜索关键词并返回精确字段路径 + 采样值 |
| `scout_export` | 导出单个 API：压缩字段文档 + 原始 JSON |
| `scout_export_all` | 批量导出所有已捕获的 API |
| `scout_peek` | 打开页面 → 监听 → 按路径匹配 API → 一步返回详情 |

### 扫描（1 个）
| 工具 | 说明 |
|------|------|
| `scout_scan` | `mode="all"` 全量扫描（API + SSR + DOM）。`mode="dom"` 关键词扫描 |

## 推荐工作流

### 🚀 快速路径（推荐）

```bash
# 1. 打开页面，从文本中选一个可见关键词
scout_open("https://www.bilibili.com")
→ 页面文本: 原神 男人领域 鬼畜 …

# 2. 滚动触发更多 API（推荐/动态流接口）
scout_act("scroll")
→ +11 APIs, 命中 feed/rcmd 推荐接口

# 3. 用关键词搜索，定位是哪个 API
scout_search("男人领域")
→ [51] GET feed/rcmd  ← 命中！

# 4. 看精确字段路径和值
scout_context("男人领域")
→ data.item[0].title = "男人领域"

# 5. 确认目标，检查请求参数、导出
scout_inspect(51)
scout_export(51)
```

**核心思路**：跳过枚举扫描（scan/apis），直接从关键词反推 → 搜索定位 API → context 给字段路径。比传统"全量扫描 → 逐个 inspect"快。

### 全量扫描（不知道关键词时）

```bash
scout_open(url)
scout_act("search", kw)      # 触发搜索 API
scout_scan(mode="all")       # 全量扫描
scout_apis()                 # 列出所有端点
scout_inspect(n)             # 逐个查看
scout_export(n)
```

### SSR 页面（丁香园等）

数据在 HTML/DOM 中，不在 XHR 里。用 `scout_search` + `scout_scan(mode="dom")`，`scout_apis()` 返回 0 是预期行为。

## 架构

```
src/web_scout/
├── server.py           # FastMCP 入口 + 19 个工具
├── state.py            # 全局状态 + 多标签页隔离
├── browser.py          # Chromium 封装 + 文本提取 + 多标签管理
├── monitor.py          # 网络监听 + JSON API 过滤 + SSR 提取 + 查询
├── dom.py              # 元素扫描 + 容器发现 + 字段提取
├── export.py           # 压缩字段文档 + 原始数据包保存
├── login.py            # 登录检测 + 手动登录等待 + 验证码处理
└── tools/
    ├── navigate.py     # 导航: open close tabs tab_switch tab_close
    ├── observe.py      # 观察: fetch screenshot elements
    ├── act.py          # 交互: act click login
    ├── discover.py     # 发现: apis inspect search context export export_all peek
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
