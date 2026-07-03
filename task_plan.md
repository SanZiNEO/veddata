# Task Plan: Web Scout v0.3 — 六份计划实现

## Goal

基于已验证的 6 份计划文档，按顺序实现 Web Scout v0.3 的全部代码变更：API 公共池架构、DOM 容器 v3 + Common Actions、AXTree 双输出 + 浏览器复用修复、scout_fetch 全量 dump、scout_act 链式四操作、scout_cookies + scout_request 新工具。

## Current Phase

Phase 1

## Phases

### Phase 1: API 公共池（PLAN_API_POOL）
- [ ] 新建 `src/web_scout/network_pool.py`（NetworkPool 类，全局单例）
- [ ] 重写 `state.py`：`_api_pool` 替代 `_monitors`；`resolve_tab(str)` 替代 `resolve_tab(int)`
- [ ] 重写 `browser.py`：CDP tab_id 为主键，移除 num 字段，新增前缀匹配
- [ ] 全工具迁移：所有 `tab: int` → `tab: str`（navigate/observe/act/discover/scan）
- **Status:** pending

### Phase 2: DOM v3 + Common Actions（PLAN_ELEMENTS_OPTIMIZE）
- [ ] `dom.py`：find_containers v3（LAYOUT 黑名单、display:none 过滤、v3 评分）
- [ ] `dom.py`：_extract_container_fields_tab 加 h[1-4] → title 映射
- [ ] `dom.py`：新增 find_common_actions() 方法（两层过滤）
- **Status:** pending

### Phase 3: AXTree + 浏览器复用修复（PLAN_OPEN_OPTIMIZE）
- [ ] `tools/navigate.py`：新增 `_ax_summary()` 函数
- [ ] `tools/navigate.py`：scout_open 新增 reuse 参数 + 清理逻辑
- [ ] `browser.py`：BrowserSession 接受 force_new 参数
- [ ] `browser.py`：_ensure_browser() 分支使用 new_env()
- **Status:** pending

### Phase 4: scout_fetch 全量 dump（PLAN_FETCH_OPTIMIZE）
- [ ] `tools/observe.py`：重写 scout_fetch（滚动到底 → 全量 AXTree → 缓存 → 分段读）
- [ ] 输出格式：[XXXX] (N chars total) + 链接位置匹配
- **Status:** pending

### Phase 5: scout_act 链式四操作（PLAN_ACT_OPTIMIZE）
- [ ] `tools/act.py`：重写 scout_act（input/scroll/click/select 链式，API 内联输出）
- [ ] 退役 scout_click
- **Status:** pending

### Phase 6: 新工具 cookies + request（PLAN.md）
- [ ] `tools/observe.py`：新增 scout_cookies
- [ ] 新建 `src/web_scout/requester.py` + `tools/discover.py` 新增 scout_request
- **Status:** pending

## Key Questions

1. 多标签页下 API 监听如何保证不丢包？（答案：每个标签页独立 `tab.listen.start()`，NetworkPool 统一存储）
2. 浏览器复用如何彻底清理？（答案：`ChromiumOptions().new_env()` 关闭旧进程）
3. tab 短 ID 匹配如何实现？（答案：前缀匹配 `tid.startswith(short_id)`）

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| NetworkPool 全局单例 + 按 tab_id 过滤 | DataPacket 原生带 pkt.tab_id，天然可区分标签页 |
| 先监听再导航为铁律 | DrissionPage 文档明确：listen.start() 之前的请求无法捕获 |
| new_env() 处理浏览器复用 | 测试验证能彻底关闭旧进程、创建全新浏览器 |
| tab: str 短 ID 前缀匹配 | 显示截断 8 位，前缀查找完整 ID |
| 输出格式含 API method + 路径 | 测试反馈：只给个数不够，AI 需要一步到位看到新 API |

## Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| 'Chromium' object has no attribute 'listen' | 1 | listen 只在 ChromiumTab，改为 `tab.listen.start()` |
| local variable 'fail' referenced before assignment | 1 | DrissionPage 4.1.1.4 bug，`listen.wait()` 加 try/except |
| _tabs 长度 ≠ tab_ids 长度（MCP 重启后） | 1 | 旧浏览器被接管但 _tabs 为空，用 new_env() 杀掉旧进程 |
| scout_apis 返回 0 API（第二次调用） | 1 | listener 挂在旧 tab 上，改成先导航再挂 listener |
| tab: str 无法精确匹配完整 CDP ID | 1 | 改为前缀匹配 `tid.startswith(input)` |

## Notes

- 所有计划已写成文档放在 `plans/` 目录
- 验证测试在 `test/` 目录，共 6 个文件
- 测试全部 PASS 后才可开始实现
