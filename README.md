# Web Scout

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
| `USER_DATA_DIR` | 临时 | 持久化用户文件夹，保留登录态 |
| `LOGIN_TIMEOUT` | `"300"` | 登录最大等待秒数 |

## 工具

| 工具 | 说明 |
|------|------|
| `scout_open` | 打开页面 → 提取全文 Markdown → 开始监听网络 |
| `scout_action` | 执行搜索、滚动等操作 |
| `scout_wait_login` | 等待用户手动登录 |
| `scout_list_apis` | 列出捕获的 API 端点 |
| `scout_inspect_api` | 查看 API 的完整请求和响应 |
| `scout_list_elements` | 列出页面元素供 AI 选择 |
| `scout_click` | 点击指定元素 |
| `scout_export` | 导出原始数据包 + 压缩字段文档 |

## 示例

```
AI: scout_open("https://xiaohongshu.com/explore")
→ "页面文本: 减脂餐 健身计划 OOTD …"

AI: scout_action("search", "减脂餐")
→ "捕获 2 个新 API"

AI: scout_list_apis()
→ [1] POST /api/search/notes  → 20 个字段

AI: scout_inspect_api(1)
→ POST https://edith.xiaohongshu.com/api/search/notes
   请求体: {"keyword": "减脂餐", "page": 1, ...}
   响应: code=0, data.items[]: 本次=20, id=..., title=...

AI: scout_export(1)
→ 字段文档 + 已保存: response/search_notes.json
```

## 架构

```
src/web_scout/
├── server.py      # FastMCP 入口 + 8 个工具
├── browser.py     # Chromium 封装 + 文本提取 + 登录检测
├── monitor.py     # 网络监听 + API 过滤 + 存储
├── dom.py         # 元素扫描 + 容器合并
└── export.py      # 压缩字段文档 + 原始数据包保存
```

## License

MIT © [ShanZhi](https://github.com/SanZiNEO)
