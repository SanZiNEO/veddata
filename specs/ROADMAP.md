# web-scout 问题与规划

## 已知问题

### 1. SSR 页面 API 少时缺乏指引

`scout_open(mode="api")` 在豆瓣返回 "APIs: 1" 时，AI 误以为没数据可爬。实际数据在 HTML 里。

**修复**: `api_count < 3` 时自动追加 `"数据可能在 HTML 中，试试 mode=dom"`。

### 2. 滚动操作粒度太粗

`scout_action("scroll")` 只支持触底，无法指定精确像素或方向。

**修复**: 扩展 `value` 参数，支持 `"top"` / `"down"` / `"300"`（精确像素）。

### 3. 文本提取可优化

当前 `browser.py` 用 `re.sub(r'<[^>]+>', '', html)` 去标签，豆瓣等页面残留导航/页脚文本。

**候选方案**:
- `trafilatura.extract(html)` — 自动去导航/页脚/广告，提取正文
- `html2text.html2text(html)` — 更干净的 Markdown 转换

### 4. 工具可发现性不足

| 工具 | 问题 |
|------|------|
| `scout_action("scroll")` | docstring 没写清楚用于无限滚动加载 |
| `scout_click` | 不知道可以点翻页按钮触发新 API |
| `scout_list_browsers` | 新加的工具，AI 不知道它的存在 |

**修复**: 补全 docstring，用典型使用场景当示例。

### 5. 缺少批量导出

`scout_export` 一次只能导一个 API。探索 5 个数据源需要调 5 次导出 + 5 次 inspect。

**修复**: 加 `scout_export_all`，遍历全部 API 记录，一次批量导出到 `response/` 目录。

### 6. 页面文本时序

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

### 7. Content-Type 过滤太窄

`filter_and_store()` 只保留 `Content-Type: application/json` 的响应。金融/天气/部分 API 接口返回 `text/plain` 或 `application/octet-stream` 但 body 是 JSON——全部被过滤掉，导致 `scout_list_apis` 返回 0。

**示例**: 富途牛牛 `quote-api/quote-v2/get-index-spark-data` 被过滤，Chrome DevTools 却能捕获 226 个请求。

**修复**: 放宽过滤条件——`application/json` 或 `text/plain` 或 `application/octet-stream`，非 JSON 的标 `[raw]`，仍然可以 inspect 和 export。

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

### 请求详情增强

当前 `scout_inspect_api` 展示的请求头不完整（如富途的 `quote-token` 自定义头不可见）。

**修复**: `monitor.py` 的 `get_api()` 输出所有请求头和响应头，不做截断。

### 重定向链

302/301 跳转的中间态不可见（如富途 `quote-api` → 302 → `www.futunn.com/403`）。

**修复**: `DataPacket` 的 `response.url` 和 `response.headers['Location']` 记录最终跳转目标和中间链。`inspect_api` 展示完整跳转路径。

### 资源类型标注

当前只标注 XHR/Fetch。`EventSource`（SSE）、`WebSocket` 也做区分标注。

**方案**: `DataPacket.resourceType` 拓展标签，`list_apis` 里标注类型。

> 以下**不做**: 请求回放（带 header 重发请求）——这是 Postman/curl 的活，web-scout 是发现工具。
