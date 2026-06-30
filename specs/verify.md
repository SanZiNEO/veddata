# scout_fetch_api / scout_inspect_dom — 验证模式工具

## 适用场景

当你已经知道要找什么（旧爬虫 API 结构变了、页面改版了），不需要走完整发现流程，直接一步拿结果对比。

| 场景 | 工具 | 一句搞定 |
|------|------|----------|
| 旧 API 结构变了 | `scout_fetch_api(url, path)` | "打开页面，给我那条搜索 API 现在的请求参数和响应结构" |
| 页面改版了 | `scout_inspect_dom(url, keyword)` | "打开页面，'后室'这个关键词现在在哪些 DOM 容器里" |

---

## scout_fetch_api

```
打开页面 → 监听网络 → 找到第一个 path 匹配的 JSON API → 直接返回完整请求参数 + 压缩响应结构。
AI 拿到后跟旧爬虫代码对比，字段增删一眼看出。
```

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `url` | str | ✅ | 目标页面 URL |
| `path_contains` | str | ❌ | API 路径关键字过滤，如 `"/search/notes"`。不传返回第一个 JSON API |
| `method` | str | ❌ | 请求方法过滤：`"GET"` / `"POST"`。不传不限制 |

### 返回格式

成功时直接输出完整 inspect 结果（同 `scout_inspect_api`）+ 压缩字段文档（同 `scout_export`）：

```
=== API 匹配 ===
URL:    POST https://edith.xiaohongshu.com/api/sns/web/v1/search/notes
Method: POST
Headers:
  Content-Type: application/json;charset=UTF-8
  x-s: XYS_...
  Cookie: a1=...; web_session=...

Body:
  {"keyword": "减脂餐", "page": 1, "page_size": 20, ...}

=== 响应结构 ===
code: 0, success: true
data.items[]: 本次=20
  id              : string = "6a38dd35..."
  display_title   : string = "减脂餐合集"
  liked_count     : string = "4.4万"
  ...
```

如果指定了 `path_contains` 但无匹配，返回 "未找到匹配的 API，已捕获 N 个 API：...（列表）"，让 AI 判断下一步。

### 实现要点

```python
# 省掉 scout_open → scout_action → scout_list_apis → scout_inspect_api 四步
# 合并为一步

@mcp.tool()
def scout_fetch_api(url: str, path_contains: str = None, method: str = None) -> str:
    # 1. 开浏览器 + 打开页面 + 开始监听
    # 2. sleep(3) 等 API 落盘
    # 3. monitor.list_apis → 找匹配的
    # 4. 找到 → inspect + export 一起返回
    # 5. 没找到 → 返回 API 列表
```

---

## scout_inspect_dom

```
打开页面 → sleep 等 DOM 稳定 → 跑 scan_by_keyword(keyword) → 直接返回匹配容器和字段。
AI 拿到后跟旧选择器对比，class 改没改一眼看出。
```

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `url` | str | ✅ | 目标页面 URL |
| `keyword` | str | ✅ | 搜索关键词 |

### 返回格式

```
关键词 '后室' 命中了 3 个容器:

[1] .rec-list[] 共 17 条
  [0] .title   : text = "人类亲手撕开了世界的BUG！《后室》远比你想象的恐怖！"
      .author  : text = "史蒂芬周大反派"
      .views   : text = "222.1万"

[2] .left-container[] 共 5 条
  [0] .title   : text = "【纯科普向】后室到底是个什么东东？..."

[3] .video-container-v1[] 共 2 条
  ...
```

### 实现要点

```python
@mcp.tool()
def scout_inspect_dom(url: str, keyword: str) -> str:
    # 1. 开浏览器 + 打开页面
    # 2. sleep(2) 等 DOM 渲染
    # 3. dom.scan_by_keyword(keyword) → 返回容器列表
    # 4. 格式化输出
```

---

## scout_close

```
关闭当前 scout_open 打开的浏览器会话，释放资源。
```

### 参数

无。

### 返回

```
"浏览器已关闭"
```

### 实现要点

```python
@mcp.tool()
def scout_close() -> str:
    global _browser
    if _browser:
        try:
            _browser.close()
        except: pass
        _browser = None
        _monitor = None
        _dom = None
        _login_pending = False
        return "浏览器已关闭"
    return "没有打开的浏览器"
```

### 使用场景

- AI 完成了发现和导出，主动释放浏览器
- 中途想换一个 URL 重新开
- `AUTO_CLOSE=false` 时手动关闭

---

## 与传统发现模式的关系

```
发现模式:  scout_open → scout_list_apis → 选 → inspect → export  （5步，AI 要做 3 次决策）
验证模式:  scout_fetch_api(url, path) → 直接出结果                （1步，AI 无决策）
```

验证模式不做搜索操作（不调 `scout_action("search")`），只监听页面加载时自然触发的 API。如果需要搜索触发新 API，还是走 `scout_open` + `scout_action` 路径。

---

## 注意事项

- 这两个工具各自独立打开一个新浏览器会话，用完即关
- 不依赖全局状态，可以和其他 `scout_open` 会话共存
- 返回的数据格式与 `scout_inspect_api` / `scout_export` / `scan_by_keyword` 完全一致
- `AUTO_CLOSE` 环境变量同样生效
