# server.py — MCP 服务入口

## 职责

FastMCP 服务启动、8 个工具注册、全局会话管理、各模块协调。

## 依赖

- `fastmcp >= 2.0`
- `browser.py` — BrowserSession
- `monitor.py` — NetworkMonitor
- `dom.py` — DOMScanner
- `login.py` — LoginDetector
- `export.py` — Exporter

## 参考

- [FastMCP 文档](https://github.com/jlowin/fastmcp)
- [SPSS MCP Server](E:\\Documents\\GitHub\\bilibili-embedded-ad-research\\.venv\\Lib\\site-packages\\spss_mcp\\) — 同款 fastmcp 项目，参考工具注册模式
- [MCP Protocol 规范](https://modelcontextprotocol.io/)

## 全局状态

```python
# 全局单例
_browser: BrowserSession | None = None
_monitor: NetworkMonitor | None = None
_dom: DOMScanner | None = None
_login: LoginDetector | None = None
_exporter: Exporter | None = None

# 会话标记
_current_url: str = ""
_current_mode: str = "auto"
_login_pending: bool = False  # 是否在等待登录
```

## 8 个工具定义

### scout_open

```python
@mcp.tool()
def scout_open(url: str, mode: str = "auto") -> str:
    """
    打开 URL，启动浏览器，提取文本，开始网络监听。
    mode: "auto" | "api" | "dom" | "text"
    """
    global _browser, _monitor, _dom, _login, _exporter
    global _current_url, _current_mode, _login_pending
    
    # 1. 关闭旧会话
    if _browser:
        try: _browser.close()
        except: pass
    
    # 2. 创建新会话
    _browser = BrowserSession()
    _current_url = url
    _current_mode = mode
    
    # 3. 打开页面
    result = _browser.open(url)
    
    # 4. 检查登录
    _login = LoginDetector(_browser.tab)
    if _login.is_login_required():
        _login_pending = True
        return "此页面需要登录，请调用 scout_wait_login() 等待登录完成"
    
    # 5. 启动网络监听
    _monitor = NetworkMonitor(_browser.tab)
    _monitor.start()
    
    # 6. 创建 DOM 扫描器
    _dom = DOMScanner(_browser.tab)
    
    # 7. 创建导出器
    _exporter = Exporter()
    
    # 8. 返回结果
    lines = [
        f"页面已打开: {result['title'] or url}",
        "",
        f"=== 页面文本 ===",
        result["text"],
        "",
        f"页面加载 API: {result['api_count']} 个",
    ]
    
    if mode == "api":
        lines.append("→ 下一步: scout_action('search', '关键词') 搜索数据")
    elif mode == "dom":
        lines.append("→ 下一步: scout_list_elements() 查看元素 或 scout_action('search', '关键词')")
    elif mode == "text":
        lines.append("→ 文本模式，已返回全文。不需要进一步操作")
    
    return "\n".join(lines)
```

### scout_action

```python
@mcp.tool()
def scout_action(action: str, value: str = None) -> str:
    """执行搜索或滚动操作"""
    global _monitor, _browser
    
    if not _browser:
        return "错误: 请先调用 scout_open"
    
    if _login_pending:
        return "错误: 请先调用 scout_wait_login() 完成登录"
    
    if action == "search" and value:
        # 找搜索框并搜索
        inputs = _browser.tab.eles('css:input[type=text], css:input[type=search], css:input[placeholder*=搜索]')
        if not inputs:
            inputs = _browser.tab.eles('css:input:not([type=hidden]):not([type=submit])')
        
        if inputs:
            input_el = None
            for inp in inputs:
                try:
                    if inp.states.is_displayed:
                        input_el = inp
                        break
                except: pass
            
            if input_el:
                input_el.clear()
                input_el.input(value)
                _browser.tab.actions.press_keys("Enter")  # 或用 input_el.input(value + '\n')
            else:
                return f"未找到可见搜索框，请用 scout_list_elements 手动选择"
        else:
            return f"未找到输入框"
    
    elif action == "scroll":
        _browser.tab.scroll.to_bottom()
    
    else:
        return f"不支持的操作: {action}"
    
    import time
    time.sleep(2)
    
    # 等待新 API
    new_count = _monitor.wait_new(timeout=3.0) if _monitor else 0
    
    return f"已执行 {action}: {value or ''}，新增 {new_count} 个 API"
```

### scout_wait_login

```python
@mcp.tool()
def scout_wait_login(timeout: int = 300) -> str:
    """等待用户手动登录"""
    global _login_pending, _browser, _monitor, _login
    
    if not _browser or not _login:
        return "错误: 请先调用 scout_open"
    
    result = _login.wait_for_login(timeout)
    
    if result:
        _login_pending = False
        # 登录成功后启动监听
        _monitor = NetworkMonitor(_browser.tab)
        _monitor.start()
        text = _browser.get_text()
        return f"登录成功！已刷新页面\n\n页面文本:\n{text[:2000]}"
    else:
        return f"登录超时（{timeout}秒），请重试"
```

### scout_list_apis

```python
@mcp.tool()
def scout_list_apis(keyword: str = None) -> str:
    """列出捕获的 API"""
    if not _monitor:
        return "错误: 请先调用 scout_open"
    
    return _monitor.list_apis(keyword=keyword)
```

### scout_inspect_api

```python
@mcp.tool()
def scout_inspect_api(index: int) -> str:
    """查看 API 详情"""
    if not _monitor:
        return "错误: 请先调用 scout_open"
    
    return _monitor.get_api(index)
```

### scout_list_elements

```python
@mcp.tool()
def scout_list_elements() -> str:
    """列出交互元素 + 容器"""
    if not _dom:
        return "错误: 请先调用 scout_open"
    
    lines = [_dom.list_elements()]
    
    # 同时扫描容器
    containers = _dom.find_containers()
    if containers:
        lines.append("")
        lines.append("---")
        lines.append(containers)
    
    return "\n".join(lines)
```

### scout_click

```python
@mcp.tool()
def scout_click(index: int) -> str:
    """点击元素"""
    if not _dom:
        return "错误: 请先调用 scout_open"
    
    result = _dom.click_element(index)
    
    import time
    time.sleep(2)
    
    new_count = _monitor.wait_new(timeout=3.0) if _monitor else 0
    
    return f"{result}，新增 {new_count} 个 API"
```

### scout_export

```python
@mcp.tool()
def scout_export(index: int, format: str = "both") -> str:
    """导出数据源"""
    global _monitor, _exporter, _browser
    
    if not _monitor or not _exporter:
        return "错误: 请先调用 scout_open"
    
    api_record = _monitor.get_api(index)
    if not api_record:
        return f"API #{index} 不存在"
    
    # 如果是指向 DOM 容器的编号，走 DOM 导出
    # （通过 _dom.find_containers() 的缓存判断）
    
    result = _exporter.export(api_record, format)
    
    # 自动关闭浏览器
    if os.environ.get("AUTO_CLOSE", "true") == "true":
        _browser.close()
    
    return result
```

## 主函数

```python
def main():
    mcp.run()

if __name__ == "__main__":
    main()
```

## 注意事项

- 全局状态用模块级变量，FastMCP 是单进程运行，安全
- 工具函数签名用类型注解，FastMCP 自动生成 schema
- 异常统一在最外层工具函数中 try/except，返回错误文本给 AI
- `scout_export` 完成后根据 `AUTO_CLOSE` 环境变量决定是否关闭浏览器
