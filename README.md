# 斥候（veddata）

<!-- mcp-name: io.github.SanZiNEO/veddata -->

一个模型上下文协议（MCP）服务器：在网页上做数据源发现 —— 捕获网络请求、提取内嵌数据、分析脚本，并通过交互与监测点跟踪数据流向。

[English](README.en.md)

## 功能

- **网络数据源**：页面发出的全部请求与响应，按接口归并并给出字段结构
- **内嵌数据**：`<script>` 标签里的 JSON 与 `window` 全局变量
- **脚本分析**：列出与搜索已加载脚本、读取源码、追踪一个值出现在哪些位置
- **交互**：点击、输入、选择、滚动，按可见文本或 `css=`、`//`（XPath）选择器定位
- **监测点**：请求监测（匹配到指定模式即记录）与 JS 断点监测（命中时抓取作用域变量快照）
- **文档结构**：DOM 树快照、关键词定位、按路径定位，全部在服务端内存中完成
- **工具链**：一次调用顺序执行多个工具（支持等待与重复），并为每个动作给出因果差分
- **页面事实**：地址、标题、正文长度、关键词命中的原文片段、可见与隐藏的组件
- **下载**：发生下载时在消息中给出文件名、保存路径、状态与大小
- **服务端留存**：结果留在服务端，返回压缩摘要，明细随时按需获取

## 环境要求

- Python 3.10 及以上
- Chrome 或 Edge（默认以有窗口模式启动，并使用持久化配置目录保留登录状态）

## 安装与使用

一次性运行（无需安装，推荐）：

```json
{
  "mcpServers": {
    "veddata": {
      "command": "uvx",
      "args": ["veddata", "--response-dir", "E:\\path\\to\\out"]
    }
  }
}
```

或先安装再使用：`uv tool install veddata`（或 `pip install veddata`），然后

```json
{
  "mcpServers": {
    "veddata": {
      "command": "veddata",
      "args": ["--response-dir", "E:\\path\\to\\out"]
    }
  }
}
```

从源码运行（开发用）：

```bash
uv venv
uv pip install -e ".[dev]"
```

客户端配置（标准输入输出）：

```json
{
  "mcpServers": {
    "veddata": {
      "command": "E:\\path\\to\\veddata\\.venv\\Scripts\\python.exe",
      "args": ["-m", "veddata.server",
               "--profile-dir", "E:\\path\\to\\profile",
               "--response-dir", "E:\\path\\to\\out"]
    }
  }
}
```

## 配置项

| 参数 | 说明 |
|------|------|
| `--profile-dir <目录>` | 浏览器配置目录（持久化，保留登录状态）。默认 `<用户数据根>/veddata/profile` |
| `--response-dir <目录>` | `ved_export`、`ved_screenshot` 的落盘目录。未配置时这两个工具在写盘时报错 |

| 环境变量 | 说明 |
|----------|------|
| `HEADLESS=true` | 无窗口模式（默认为有窗口） |
| `BROWSER_PATH <路径>` | 指定浏览器可执行文件（填 `edge` 表示使用 Edge） |
| `BROWSER_ADDRESS <地址>` | 接管已在运行的浏览器（调试协议地址），而不是自行启动 |

## 工具

### 会话与标签页

- **ved_open** — 启动会话（自行启动一个普通 Chrome 并通过调试协议接管）
- **ved_status** — 当前页面事实、标签页清单、已捕获条数、状态账本
- **ved_tabs**、**ved_tab_switch**、**ved_tab_close** — 标签页清单、切换、关闭
- **ved_close** — 关闭浏览器并清空捕获数据

### 导航与读取

- **ved_goto** — 导航，返回文档结构、数据源预览与页面事实
- **ved_fetch** — 取当前页正文（分页）
- **ved_dom_tree**、**ved_dom_search**、**ved_dom_locate** — 树快照、关键词、路径
- **ved_console** — 执行 JS 或读取控制台消息
- **ved_cookies**、**ved_screenshot** — cookie 与截图落盘

### 交互

- **ved_act** — `input`、`click`、`select`、`scroll`；可单步或链式；`target` 支持可见文本、`css=` 或 `//`

### 数据源

- **ved_apis**、**ved_inspect** — 捕获清单与单条详情（请求头、响应体、字段结构）
- **ved_export**、**ved_export_all** — 导出到磁盘（原始或精简）
- **ved_peek** — 打开网址并直接返回数据源清单
- **ved_request** — 重放已捕获的接口或发送自定义请求（自动带上 cookie）
- **ved_search**、**ved_context**、**ved_trace_value** — 跨网络、内嵌、脚本、全局变量的搜索与追踪

### 脚本

- **ved_list_scripts**、**ved_search_scripts**、**ved_script_source** — 清单、搜索、源码

### 监测点

- **ved_watch** — 注册、列表、收集、删除；分为请求与 JS 两类；命中快照留在服务端

### 扫描

- **ved_scan** — 一次性汇总网络、文档结构与内嵌数据

### 工具链

- **ved_chain** — 顺序执行多个工具；等待支持毫秒、网络命中、网络静默、元素可见性；重复块支持一层

## 行为说明

- **只陈述事实**：输出说明有什么，不含判断与下一步提示；页面状态以地址、标题、正文长度、关键词命中片段、可见组件等事实呈现。
- **结果留在服务端**：返回压缩摘要与分页页脚，明细用 `ved_apis`、`ved_inspect`、`ved_watch(collect)` 等按需获取。
- **状态观测**：发生在工具之外的变化（页面自行跳转、标签页增删）之后，依赖活状态的工具会返回一条事实说明而不执行；`ved_status`、`ved_tabs` 会重新建立观测。
- **人机协作**：界面可见，登录或验证由用户在窗口中完成；工具照实报告当前页面事实。
- **浏览器生命周期**：自行启动的浏览器由 `ved_close` 关闭；通过 `BROWSER_ADDRESS` 接管的仅断开连接。

## 示例：没有接口文档的站点，怎么拿到下载直链

以 svgrepo 为例（该站点没有公开接口文档，AI 只能自己侦察）。一条工具链跑完：

```json
[
  {"tool": "ved_open"},
  {"tool": "ved_goto", "args": {"url": "https://www.svgrepo.com/vectors/arrow/"}},
  {"tool": "ved_goto", "args": {"url": "https://www.svgrepo.com/svg/535197/arrow-u-up-left"}},
  {"tool": "ved_act",  "args": {"action": "click", "target": "css=a[href*='/download/']"}}
]
```

消息里直接给出事实（动作、因果、落盘位置）：

```
[click] Clicked 'css=a[href*='/download/']' → +1 new APIs
    GET    https://www.svgrepo.com/_next/data/XJiZPe18H5paekHV…/tools.json
download: arrow-u-up-left-svgrepo-com.svg → E:\Downloads\arrow-u-up-left-svgrepo-com.svg (completed, 399 B)
```

## 开发

```bash
pytest tests -q
python scripts/smoke.py
```

## 许可

MIT License，详见 [LICENSE](LICENSE)。

## 免责声明

本项目仅用于学习、研究、技术交流与合法合规的自动化测试，**不得用于任何违法、侵权或违背公序良俗的用途**。使用前请完整阅读本声明；**下载、安装、运行或以任何方式使用本项目，即视为已阅读、理解并同意本声明的全部内容**。如不同意，请立即停止使用并删除本项目。

1. **合规责任由使用者自负**。使用者应自行确认并遵守：目标网站的服务条款、`robots.txt` 与使用规则；所在国家或地区的法律法规（包括但不限于网络安全、数据安全、个人信息保护、著作权、反不正当竞争、计算机信息系统相关法律）；以及任何适用的行业规范与合同约定。
2. **禁止用途**。不得用于：未经授权访问、干扰或破坏他人系统与数据；绕过技术保护措施或访问控制；大规模抓取、囤积或转售他人数据；侵犯他人知识产权、商业秘密或个人隐私；任何形式的欺诈、骚扰、垃圾信息或其他恶意行为。
3. **风险自担**。使用本项目可能导致账号被封禁、访问受限、服务中断、数据丢失或其他损失，上述风险与后果由使用者自行承担。
4. **无担保**。本项目按「原样」（AS IS）提供，作者不对其适用性、可靠性、准确性、安全性或不侵权作出任何明示或默示的担保，也不承诺任何功能可用、持续可用或不会被目标站点检测。
5. **责任限制**。在适用法律允许的最大范围内，作者与贡献者不对因使用或无法使用本项目而产生的任何直接、间接、附带、特殊、惩罚性或后果性损害（包括但不限于利润损失、数据丢失、业务中断、第三方索赔、行政处罚或法律责任）承担任何责任。
6. **不构成法律意见**。本项目不提供任何法律意见或合规承诺；涉及合规判断请咨询专业律师。
7. **对第三方的主张由使用者承担**。因使用者的行为引发的任何第三方主张、争议、投诉或索赔，由使用者自行处理并承担全部责任，与作者及贡献者无关。
8. **权利保留**。作者保留随时修改、暂停或终止本项目的权利，且无需事先通知；本声明亦可随时更新，更新后的版本自发布之日起生效。
