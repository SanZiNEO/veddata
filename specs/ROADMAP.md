# web-scout 问题与规划

## 已知问题

### 0. `scout_open` 太重，需拆分

**现状**: `scout_open` 把打开页面、文本提取、登录检测、API 监听、DOM 扫描全部包在一个函数里。不管什么 mode，都会启动监听等 3 秒、创建 DOM 扫描器——`mode=text` 时全是无用功。

**问题**:
- `mode=text` 本不需要 API 和 DOM，但额外等了 3 秒
- 状态臃肿，难以调试
- API 为 0 时输出 `"→ Next: scout_action('search', 'keyword')"` 误导 AI

**新设计**:

```
scout_open(url)
  └─ 打开浏览器 + 访问页面 + 等 DOM 渲染 + 提取全文 Markdown
  └─ 检测登录墙
  └─ 返回: 标题 + 全文 Markdown（去掉 mode 参数，默认就是 text）

scout_analyze()
  └─ AI 读文本后主动调用（不传参数）
  └─ 启动网络监听 + 等 3 秒 + 捕获全部 API
  └─ 扫描 DOM 容器
  └─ 返回: API 列表 + DOM 容器列表
```

**去掉 mode 参数。** 原因是：AI 第一步永远应该是读文本判断"这页面能不能用"——富途停服公告就是典型。如果默认 text，读完秒出结论，不需要 mode=api 额外等 3 秒监听然后看到 0 个 API 再回头读文本。

**为什么 `analyze` 不传关键词:**

analyze 是全量扫描——启动监听、等 API 落盘、扫 DOM 容器，一次做完。关键词过滤复用已有的 `scout_search`，不重复造逻辑。好处：

- analyze 一次，AI 可以用 `scout_search` 搜多个关键词——不用每次换词都重新等 3 秒
- analyze 不包含过滤逻辑，保持简单

```
scout_open(url)      → 文本：富途停服公告
AI 读文本判断站点不可用，流程结束

scout_open(url)      → 文本：减脂餐 健身计划 周末去哪儿
AI 选词 "减脂餐"
scout_analyze()       → APIs: 5, DOM: 3
scout_search("减脂餐") → 从已捕获数据中过滤出匹配的
scout_inspect_api(1)   → 深入
```

**引导性消息全部删除。** `scout_open` 不输出 `"→ Next: ..."`，由 AI 根据文本内容自行判断。

### 1. 滚动操作粒度太粗

`scout_action("scroll")` 只支持触底，无法指定精确像素或方向。

**修复**: 扩展 `value` 参数，支持 `"top"` / `"down"` / `"300"`（精确像素）。

### 2. 文本提取可优化

当前 `browser.py` 用 `re.sub(r'<[^>]+>', '', html)` 去标签，豆瓣等页面残留导航/页脚文本。

**候选方案**:
- `trafilatura.extract(html)` — 自动去导航/页脚/广告，提取正文
- `html2text.html2text(html)` — 更干净的 Markdown 转换

### 3. 工具可发现性不足

| 工具 | 问题 |
|------|------|
| `scout_action("scroll")` | docstring 没写清楚用于无限滚动加载 |
| `scout_click` | 不知道可以点翻页按钮触发新 API |
| `scout_list_browsers` | 新加的工具，AI 不知道它的存在 |

**修复**: 补全 docstring，用典型使用场景当示例。

### 4. 缺少批量导出

`scout_export` 一次只能导一个 API。探索 5 个数据源需要调 5 次导出 + 5 次 inspect。

**修复**: 加 `scout_export_all`，遍历全部 API 记录，一次批量导出到 `response/` 目录。

### 5. 页面文本时序

`get_text()` 在 DOM 未完全稳定时截取，豆瓣话题广场的阅读数可能还没渲染。

**修复**: `scout_open` 中 `tab.wait(2)` 或 `tab.wait.ele_loaded('a, button, img')` 等待 DOM 稳定后再提取文本。

---

## 规划中

### 滚动智能模式

```
scout_action("scroll", "smart") → 自动判断:
  - 页面有无限滚动 → 持续触底直到无新内容
  - 页面有翻页按钮 → 自动找 next/下一页
  - 都没有 → fallback 到手动模式
```

需要区分"页面有分页器"和"页面有懒加载"两种模式，做一步需要额外逻辑判断。

### fetch 文本提取优化

- 替换 `re.sub` 裸去标签方案
- 调研 `trafilatura` 对中文页面的效果
- 保留当前方案作为 fallback

### 多浏览器管理

- `scout_list_browsers()` 已实现（端口池 9222-9231 探测）
- 后续可由 AI 自动关闭空闲浏览器、选择最优端口

### 通用验证弹窗

已添加 31 个选择器覆盖阿里 WAF / reCAPTCHA / hCaptcha / Turnstile / 极验 / 通用文本。后续如有遗漏继续追加。

### 6. Content-Type 过滤 + 监听失效（🔴 富途+天天基金实测）

**分两个子问题:**

**6a. Content-Type 过滤太窄** — `filter_and_store()` 只保留 `application/json`。金融站点 `rankhandler.aspx` 返回 `text/plain` 但 body 是 JSON——被过滤掉。放宽到 `text/plain` + `application/octet-stream` 即可。

**6b. 监听本身可能失效** — 天天基金两个页面都显示 `APIs: 0`，Chrome DevTools 却抓到了 `rankhandler.aspx`。根因有三层:
- `listen.start()` 在页面加载**之后**启动，同步请求已发完
- **JSONP 走 `<script>` 标签加载，不走 XHR/Fetch — 需确认 DrissionPage `listen` 是否订阅了 `Network.responseReceived` 中 `resourceType=Script` 的请求**（天天基金 `rankhandler.aspx` 就是 `<script>` 动态插入的 JSONP）
- 请求在 `<iframe>` 子帧内，`listen` 未监听子帧

**修复**: 6a 放宽 Content-Type；6b 确认 DrissionPage `listen` 对 `<script>` 资源（resourceType=Script）的捕获能力。如果不支持，通过 `tab.run_cdp('Network.enable')` 直接走 CDP 底层订阅所有网络事件，不依赖 `listen` 的高层封装。

### 7. SSR 页面内嵌 JSON 未捕获（🔴 知乎实测）

知乎/小红书等 SPA 在 HTML 中嵌入 `window.__INITIAL_STATE__={...}`，数据在页面源码里但不走 API 请求。当前 API 监听拿不到，DOM 扫描忽略 `<script>` 标签内容，导致这整块数据源完全漏掉。

**修复**: `scout_open` 文本提取后追加一步——`tab.run_js()` 提取 `window.__INITIAL_STATE__` 和类似全局变量，单列为第三种数据源（API / DOM / Embedded JSON）。

### 8. Export 状态丢失（🔴 知乎实测）

`scout_open` 成功后调 `scout_export` 报 `"call scout_open first"`。`_exporter` 或 `_monitor` 全局变量在工具间丢失。

**修复**: 排查 FastMCP 进程模型是否在每次工具调用时重置模块级变量。如确有此问题，改全局变量为文件级缓存或 session ID 关联。

### 9. 滚动结果验证缺失

`scout_action("scroll")` 执行后无反馈——AI 不知道是否触发了新 API、页面是否到底。知乎测试中滚动了但不清楚是否有新数据。

**修复**: `scroll` 操作后自动 `wait_new(timeout=2)` 并返回 "新增 N 个 API，当前页 DOM 容器变化 M 个"。

### 10. 无请求类型过滤（🔴 B站实测）

`list_apis` 列出了所有请求，B站首页 33 个中大量是图片/CSS/SVG（#10-#26 全是 banner 图），干扰严重。

**修复**: `filter_and_store` 先按 `resourceType=XHR/Fetch` 过滤，再按 Content-Type 筛选 JSON。图片/css/svg 直接跳过，不存储。

### 11. 响应体截断缺少选项（🔴 B站实测）

B站 `feed/rcmd` 返回 607 字段，截断 2000 字符后看不到完整 item 数组结构。

**修复**: `inspect_api` 提供两种模式：
- `preview`（默认）: 截断摘要，展示请求头 + 响应前 N 字符
- `full`（可选）: 完整展开第一个 item 的字段结构（用压缩算法，非原始 JSON）

---

## 规划中（讨论但未定）

### 截图工具

`tab.get_screenshot(path, name, full_page=True/False)` 一行实现整页/可视区截图。

**用途**:
- 调试确认页面加载状态
- 验证搜索/点击操作结果
- 导出字段文档附带页面截图

**涉及工具**: `scout_screenshot(name, full_page)`

### 元素截图

`ele.get_screenshot()` 对单个元素截图，可用于确认 DOM 容器是否正确。

**涉及工具**: 可在 `scout_screenshot` 中通过 `selector` 参数指定元素。

### DOM 扫描加速

DrissionPage 的 `s_eles()` 先将 DOM 转为**静态快照**再查找，消除 CDP 往返开销。163.com 实测 4s → 0.28s（14x）。

> ⚠️ 静态快照会丢失动态内容：JS 注入的文本、:hover/:focus 伪类状态、事件绑定后的属性变化。仅适用于页面已完全渲染且无后续 DOM 操作的场景。

**使用时机**: 当 `find_containers` 或 `inspect_container` 在 Python 侧循环调 `eles()` 且耗时 > 1s 时，改为一层 `s_eles()` 拿静态快照，后续查找全走本地。

### 等待策略优化

当前 `scout_open` 用 `time.sleep(3)` 硬等 DOM 加载。应改为 `wait_until()`：

```python
tab.wait_until(lambda: bool(tab.ele('a, button, input', timeout=1)))
```

不阻塞固定时间，DOM 就绪后立刻返回。

### 调试工具

`tree(ele)` 打印 DOM 树结构，可用于 `inspect_container` 输出前验证容器选择是否正确。

### 嵌套 DOM 扫描

当前容器扫描只做一层——`<table>` 内 `<td>` 的合并单元格、`<ul>` 内的嵌套 `<ul>` 等层级结构看不全。

**方案**: `tab.run_js()` 传递归函数，每遇到 `<table>` / `<ul>` / `<ol>` 多做一层展开，输出缩进层级结构。复杂度高，低优先级。

### 请求详情增强（🔴 富途实测确认）

当前 `scout_inspect_api` 展示的请求头不完整（如富途的 `quote-token` 自定义头不可见）。

**修复**: `monitor.py` 的 `get_api()` 输出所有请求头和响应头，不做截断；`scout_export` 保存的原始响应体不截断（当前限 2000 字符，天天基金 `rankhandler.aspx` 的完整 JSONP 被截断看不到 `allRecords` 分页信息）。

### 重定向链（🔴 富途实测确认）

302/301 跳转的中间态不可见（如富途 `quote-api` → 302 → `www.futunn.com/403`）。

**修复**: `DataPacket` 的 `response.url` 和 `response.headers['Location']` 记录最终跳转目标和中间链。`inspect_api` 展示完整跳转路径。

### 资源类型标注（🟡）

当前只标注 XHR/Fetch。`EventSource`（SSE）、`WebSocket` 也做区分标注。

**方案**: `DataPacket.resourceType` 拓展标签，`list_apis` 里标注类型。

> 以下**不做**: 请求回放（带 header 重发请求）——这是 Postman/curl 的活，web-scout 是发现工具。
> 以下**不做**: 鉴权/签名线索分析（x-s、x-zse-93 等）——这是逆向工程的活，不是发现工具。
