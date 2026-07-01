# 012: 多浏览器管理 — 端口池增强

> **来源**: ROADMAP.md 规划中 "多浏览器管理"
> **优先级**: P2（增强可用性，非阻塞）
> **影响范围**: `browser.py` · `server.py`

---

## 一、现状

端口池设计已经存在且工作正常：

- `browser.py`: `BrowserSession.__init__()` 遍历端口 9222-9231（10 个），取第一个可用
- `scout_list_browsers()`: 列出所有 10 个端口的状态（活跃/空闲）
- `scout_close()`: 关闭当前浏览器会话

**缺失能力**:

| 场景 | 是否支持 |
|------|---------|
| 查看所有端口状态 | ✅ `scout_list_browsers()` |
| 关闭当前会话 | ✅ `scout_close()` |
| 关闭指定端口的浏览器 | ❌ 不支持 |
| 所有 10 个端口占满时的提示 | ❌ 当前抛 `RuntimeError` |

---

## 二、设计

### 2.1 `scout_close` 增加 `port` 参数

```python
@mcp.tool()
def scout_close(port: int | None = None) -> str:
    """Close a browser session.

    Without arguments: closes the current session tracked by scout_open.
    With a port number: closes the browser on the specified port (9222-9231),
    regardless of whether it's the "current" session.

    Args:
        port: Optional port number to close. If omitted, closes current session.

    Returns:
        Status message.
    """
    global _browser, _monitor, _dom, _login_pending

    if port is not None:
        if not 9222 <= port <= 9231:
            return f"Port {port} out of range (9222-9231)."

        from DrissionPage import Chromium, ChromiumOptions
        try:
            co = ChromiumOptions().set_address(f"127.0.0.1:{port}")
            browser = Chromium(co)
            browser.quit()
            return f"Browser on port {port} closed."
        except Exception as e:
            return f"Port {port} is already free or could not be closed: {e}"

    # 关闭当前会话（现有逻辑）
    if not _browser:
        return "No open browser session."

    try:
        _browser.close()
    except Exception:
        pass

    _browser = None
    _monitor = None
    _dom = None
    _login_pending = False

    return "Browser closed."
```

### 2.2 `BrowserSession` 端口耗尽时友好提示

**现状** (`browser.py:44`):

```python
raise RuntimeError("No available browser port in 9222-9231")
```

**改进**:

```python
raise RuntimeError(
    "所有浏览器端口 (9222-9231) 均被占用。\n"
    "请调用 scout_list_browsers() 查看占用情况，"
    "然后使用 scout_close(port=N) 关闭空闲浏览器释放端口。"
)
```

### 2.3 无须参考 weibo_car 项目

weibo_car 使用 `ChromiumPage` 单实例模式，无需端口池。web-scout 的 10 端口固定池已经是更完善的设计，只需增强关闭能力。

---

## 三、文件改动汇总

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/web_scout/server.py` | `scout_close` 增加 `port` 参数 | ~15 行 |
| `src/web_scout/browser.py` | `RuntimeError` 消息增加操作指引 | ~3 行 |
