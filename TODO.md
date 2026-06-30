# Web Scout — 实现任务清单

按顺序实现，每个任务完成后可独立验证。

## 1. 项目初始化
- [ ] 创建 `src/web_scout/` 目录结构
- [ ] `pip install -e .` 跑通
- [ ] `fastmcp` 空服务能启动

## 2. browser.py — 浏览器模块
- [ ] 启动 Chromium 浏览器（读取 HEADLESS 等环境变量）
- [ ] 打开 URL（`tab.get(url)`，处理超时和加载失败）
- [ ] 提取页面全文 Markdown（去掉 script/style/nav/footer/header）
- [ ] 关闭浏览器 / 复用会话

## 3. monitor.py — 网络监听模块
- [ ] 开始监听（`tab.listen.start()`，只监听 XHR/Fetch）
- [ ] 停止监听
- [ ] 过滤 API：`Content-Type: application/json`
- [ ] 存储 API 记录（URL / method / headers / params / body / 响应体）
- [ ] 去重（相同 URL+params 的请求合并计数）
- [ ] 列出 API 列表
- [ ] 获取单个 API 详情

## 4. dom.py — DOM 扫描模块
- [ ] 扫描交互元素（`a` / `button` / `input`），返回列表
- [ ] 点击元素
- [ ] 相似合并：找 ≥3 个 tag+class 相同的兄弟元素作为容器
- [ ] 取第一个容器展开内部字段（文本/图片/链接）
- [ ] 字段名推断（从 class 取最后一段）
- [ ] 导出 DOM 容器字段表

## 5. login.py — 登录检测模块
- [ ] 检测登录墙（URL 含 /login 或页面有登录弹窗）
- [ ] 等待 URL 离开登录页
- [ ] 检测验证弹窗（`.nc_wrapper` / `text=安全验证` / `text=请通过验证`）
- [ ] 登录成功后刷新页面

## 6. export.py — 导出模块
- [ ] JSON 递归展开（只取数组第一项）
- [ ] 类型推断（int/float/bool/string/null/list）
- [ ] 差异表生成（对比后续 item 与第一项的不同字段）
- [ ] 计数标注（数组长度 + 关联 count 字段 + 分页参数）
- [ ] 原始数据包保存到 `response/` 目录
- [ ] API URL → 文件名（取 path 最后两段）
- [ ] 压缩版字段文档输出

## 7. server.py — MCP 服务
- [ ] 全局会话状态（浏览器实例 + API 记录列表）
- [ ] 8 个工具注册
- [ ] 工具间状态传递（session 复用）
- [ ] 异常处理和错误返回
- [ ] `fastmcp` 启动入口

## 8. 联调
- [ ] 小红书首页 → 搜索 → 导出 API
- [ ] B站视频页 → 扫描 DOM 容器
- [ ] 需要登录的页面 → 登录检测 → 等待登录
