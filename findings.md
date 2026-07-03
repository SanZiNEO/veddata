# Findings & Decisions — Web Scout v0.3

## Requirements

- 从 plans/ 目录的 6 份文档实现 Web Scout v0.3
- 所有参数需经过测试验证，不直接照搬计划中的伪代码
- 工具总数 20（19 − 1 scout_click + 2 cookies/request）
- DrissionPage 版本 4.1.1.4

## Research Findings

### DrissionPage 关键 API 行为

| API | 行为 | 文档来源 |
|-----|------|---------|
| `tab.listen.start()` | 监听器挂在 **ChromiumTab** 上，不是 Chromium | DrissionPage 文档 |
| `tab.listen.start()` 必须在导航前调用 | `listen.start()` 之前的数据包获取不到 | DrissionPage 文档 "要先启动监听，再执行动作" |
| `DataPacket.tab_id` | 每个包原生携带产生它的标签页 ID | DataPacket 对象属性表 |
| `ChromiumOptions().new_env()` | 指定端口已有浏览器则自动关闭再启动新的 | 文档 "创建全新的浏览器" 章节 |
| `tab.cookies()` | 返回 `[{"name","value","domain"},...]` | SessionPage API 参考 |
| `page.set.cookies(dict)` | SessionPage 接收 `{name: value}` 格式 | 文档 Cookie 操作 |
| `browser.states.is_existed` | 检查 CDP 连接是否建立过，不是检查进程存活 | `_units/states.py` 源码 |

### 多标签页 API 隔离（测试验证）

三个标签页（首页/番剧页/搜索页）分别启动监听后，每个标签页的 API 都有独立的 `pkt.tab_id`。三个 ID 互不重叠。按 `tab_id` 过滤可完美隔离：

```
Tab A (首页)   : 2DA9F467 → 70 条 API
Tab B (番剧页) : 90170401 → 44 条 API
Tab C (搜索页) : CAA9C750 → 31 条 API
中途交互产生的 API → 全部归入 Tab A 的 tab_id
```

### SessionPage 重放验证

Weibo 评论 API 重放流程验证通过：
1. 浏览器捕获 → `GET /ajax/statuses/buildComments` (status=200)
2. SessionPage 重放 → status=200, ok=1, 总评论 354
3. 翻页测试 → `max_id` 参数替换后获取第二页 20 条评论
4. 导出 → 原始 JSON 148KB + 字段压缩文档 120KB

### 验证测试结果汇总

| 测试文件 | PASS | FAIL | 对应计划 |
|---------|------|------|---------|
| `test_api_pool.py` | 10 | 0 | PLAN_API_POOL |
| `test_elements.py` | 11 | 0 | PLAN_ELEMENTS_OPTIMIZE |
| `test_open.py` | 22 | 1（_tabs 同步为代码 bug） | PLAN_OPEN_OPTIMIZE |
| `test_fetch.py` | 18 | 0 | PLAN_FETCH_OPTIMIZE |
| `test_act.py` | 12 | 1（过滤 API 为 0 正常行为） | PLAN_ACT_OPTIMIZE |
| `test_plan.py` | 12 | 1（Exporter.compact 输出短） | PLAN.md |

## Technical Decisions

| Decision | Rationale |
|----------|-----------|
| NetworkPool 全局单例 + 按 tab_id 过滤 | DataPacket 原生带 `pkt.tab_id`，天然可区分 |
| 先监听再导航为铁律 | 文档明确：`listen.start()` 之前的请求无法捕获 |
| `new_env()` 处理浏览器复用 | 测试验证能彻底关闭旧进程、创建全新浏览器 |
| tab 短 ID 前缀匹配 | 显示截断 8 位，前缀匹配完整 ID |
| 每步输出 API method + 路径 | 测试反馈：只给个数不够，AI 需要一步到位 |
| 元素定位用文本（find_el_by_text） | 和 Common Actions 输出对齐，AI 不用记 CSS |
| `scout_click` 退役合并到 `scout_act` | 统一入口，减少工具数 |
| `scout_fetch` 全量 dump + 缓存文件 | 滚动到底 → AXTree → innerText → 写 JSON → 分段读 |

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| `'Chromium' object has no attribute 'listen'` | listen 只在 ChromiumTab，`browser.listen` 改为 `tab.listen` |
| `local variable 'fail' referenced before assignment` | DrissionPage 4.1.1.4 的 `listener.py:121` bug，`listen.wait()` 加 try/except |
| MCP 重启后 `_tabs` 和 `tab_ids` 不同步 | `new_env()` 杀掉旧进程，新 `BrowserSession` 从 0 开始 |
| 第二次 `scout_open` API 捕获为 0 | listener 挂在旧 tab 上，`open()` 创建了新 tab。修复：先 `open()` 再挂 listener |
| `tab: str` 无法精确匹配完整 CDP UUID | 改为前缀匹配 `tid.startswith(input)` |
| SessionPage 重放参数重复 | `url` 已含 query string 又传 `params=`，改为 `url.split("?")[0]` |
| Exporter.compact() 输出只有 20 字 | Weibo 评论响应结构复杂，compact 算法未完全展开 |

## Resources

- DrissionPage 文档：https://www.drissionpage.cn/
- 监听网络数据：https://www.drissionpage.cn/ChromiumPage/listener/
- SessionPage API：https://www.drissionpage.cn/SessionPage/intro
- 创建全新浏览器：https://www.drissionpage.cn/ChromiumPage/connection/
- 计划文档：`E:\Documents\GitHub\web-scout\plans\`
- 验证测试：`E:\Documents\GitHub\web-scout\test\`
- biliCrawler 参考（WBI 签名）：`E:\Documents\GitHub\biliCrawler\src\sign.py`
- weiibo_ad 参考（微博评论翻页）：`E:\Documents\GitHub\weiibo_ad\src\crawler\comments.py`

## Visual/Browser Findings

- B站搜索页 Common Actions 测试结果：搜索 input + button、排序（综合排序/最多播放等）、筛选、上一页/下一页共 6 个操作全部识别
- B站首页 60% 链接是导航噪音（nav/header/footer 内），AXTree 过滤 ignored 节点后噪音大幅减少
- new_env() 测试：旧浏览器 7 个标签页，new_env() 后新浏览器 1 个标签页，旧 ID 全部消失
- 微博 cookie 测试：8 个 cookie 含 `XSRF-TOKEN`，`X-XSRF-TOKEN` header 验证通过
