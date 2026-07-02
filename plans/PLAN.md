# Web Scout 轻量调试工具计划

## 目录

1. [scout_request — 快速请求调试](#1-scout_request)
2. [scout_cookies — Cookie 查看](#2-scout_cookies)
3. [scout_open 增强 — 预扫描常见交互元素](#3-scout_open-增强)
4. [SessionPage API 参考](#4-sessionpage-api-参考)

---

## 1. scout_request

### 动机

`scout_inspect` 能看 API 的请求参数和响应结构，但不能改参数重发。AI 拿到接口信息后想验证翻页、切换参数，没有工具可用。

### 方案

基于 DrissionPage 的 `SessionPage`（不从浏览器发请求，快），新增 `scout_request`，支持两种调用方式：

| 方式 | 参数 | 说明 |
|------|------|------|
| 重放 | `index=3, params='{"page":2}'` | 从 monitor 取 API #3 的原始 url/method/headers，覆盖指定参数后重发 |
| 手动 | `url="...", method="POST", body="...", params="..."` | 完全自定义请求 |

Cookie 自动从当前 Tab 同步（`tab.cookies()` → `page.set.cookies()`），保持登录态。

### 工具签名

```
scout_request(
    index: int = 0,           # API ID（从 scout_apis 输出），0 表示手动模式
    method: str = "GET",      # 手动模式的请求方法（GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS）
    url: str = "",            # 手动模式的目标 URL
    params: str = "",         # JSON 字符串，覆盖/追加请求参数
    body: str = "",           # JSON 字符串，POST/PUT/PATCH 请求体
    headers: str = "",        # JSON 字符串，覆盖/追加请求头
    tab: int = 0,             # 哪个 Tab 拿 cookie
)
```

### 返回格式

```
[Tab #1] https://example.com/
Status: 200 OK  |  Time: 234ms

=== Request ===
GET https://api.example.com/v1/search?page=2

=== Response Headers ===
  Content-Type: application/json
  Content-Length: 12345

=== Response Body (first 3000 chars) ===
{"code":0,"data":{"items":[...]}}
```

### 实现要点

- 新建 `src/web_scout/requester.py`，封装 SessionPage + cookie 同步 + 请求执行 + 结果格式化
- 核心逻辑：
  1. 解析参数（index 模式从 monitor 取记录；手动模式直接使用 url/method）
  2. 从 `state._browser.get_current_tab().cookies()` 取 cookie
  3. 创建 `SessionPage()` → 设置 cookie/headers → 发请求
  4. 格式化返回：状态码 + 耗时 + 响应头摘要 + 响应体截断
- `scout_request` 放入 `tools/discover.py`（与 inspect/export 同类）
- 处理边界：超时、SSL 错误、非 2xx 状态码
- 文件数：+1，工具数：+1

---

## 2. scout_cookies

### 动机

AI 在发 `scout_request` 前需要确认登录态有效。

### 方案

透传 DrissionPage 原生的 `tab.cookies()` 参数：

```
scout_cookies(
    all_domains: bool = False,  # False=仅当前域名，True=所有域名
    all_info: bool = False,     # False=仅 name/value/domain，True=含 path/httpOnly/secure/expires
    tab: int = 0,               # 查看哪个 Tab 的 cookie
)
```

### 返回格式（all_info=False）

```
[Tab #1] https://example.com/
Cookies (3 total, current domain only):

  SESSDATA  =  abc123...def  (.bilibili.com)
  bili_jct  =  xyz789         (.bilibili.com)
  buvid3    =  12345...       (.bilibili.com)
```

### 实现要点

- 放入 `tools/observe.py`
- 直接调 `tab.cookies(all_domains, all_info)`
- 格式化输出：表格对齐
- 如有 session/token/jwt 类关键 cookie，高亮提示
- 文件数：0（改现有），工具数：+1

---

## 3. scout_open 增强

### 动机

当前 `scout_open` 只输出页面文本，AI 要额外调 `scout_elements()` 才能知道哪些可交互。把常见 UI 控件扫描内嵌到 open 中，省掉一步。

### 方案

页面打开后跑一段轻量 JS，扫 `textContent || placeholder` 匹配常见控件关键词。实测 0.003s，比 `s_ele()`（0.01s）还快，且能覆盖 input placeholder。

关键词列表（按标签类型分）：

| 标签 | 关键词 |
|------|--------|
| input | 搜索, search |
| a | 下一页, 上一页, 登录, 注册, 换一换, 刷新, 筛选, 更多, next, prev, login, register, refresh, filter |
| button | 下一页, 上一页, 登录, 注册, 提交, 确定, 取消, 加载更多, next, prev, login, submit, load more |

### 实现代码

```python
def _scan_common_elements(tab) -> str:
    import json
    js = """
    var keywords = {
        'input': ['搜索','search'],
        'a': ['下一页','上一页','登录','注册','换一换','刷新','筛选','更多',
              'next','prev','login','register','refresh','filter'],
        'button': ['下一页','上一页','登录','注册','提交','确定','取消','加载更多',
                   'next','prev','login','submit','load more'],
    };
    var results = [];
    for (var tag in keywords) {
        var kws = keywords[tag];
        var els = document.querySelectorAll(tag);
        for (var i = 0; i < els.length && i < 300; i++) {
            var el = els[i];
            var style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            var text = (el.textContent || el.placeholder || '').trim().substring(0, 40);
            if (!text) continue;
            for (var k = 0; k < kws.length; k++) {
                if (text.indexOf(kws[k]) !== -1) {
                    results.push({
                        kw: kws[k], tag: tag,
                        id: el.id || '',
                        cls: (el.className || '').substring(0, 30),
                        text: text
                    });
                    break;
                }
            }
        }
    }
    return JSON.stringify(results);
    """
    try:
        found = json.loads(tab.run_js(js))
    except Exception:
        return ""
    if not found:
        return ""
    lines = []
    for f in found:
        id_str = f"#{f['id']}" if f['id'] else ""
        cls_str = f".{f['cls']}" if f['cls'] else ""
        lines.append(f"  [{f['kw']}] {f['tag']}{id_str}{cls_str} \"{f['text']}\"")
    return "=== Common Elements ===\n" + "\n".join(lines)
```

### 插入位置

`scout_open` 中替换 `_time.sleep(3)` 逻辑：打开页面后先 `_time.sleep(1)` 等基础渲染，然后调 `_scan_common_elements()`，有结果直接返回，不再硬等 3 秒。

### 输出格式

在现有 "=== Page Text ===" 后追加：

```
=== Common Elements ===
  [搜索] button.search-btn "搜索"
  [搜索] input#keyword "输入关键字搜索"
  [下一页] button.pagination-btn "下一页"
```

### 实现要点

- 改动 `tools/navigate.py`，新增 `_scan_common_elements()` 函数
- JS 同时扫 `textContent` 和 `placeholder`/`aria-label`
- 实测耗时 0.003s，无需优化
- 替换 `sleep(3)` → `sleep(1)` + JS 扫描
- 文件数：0（改现有），工具数：0

---

## 实施顺序

| # | 内容 | 涉及文件 | 
|---|------|---------|
| 1 | `scout_cookies` | `tools/observe.py` |
| 2 | `requester.py` + `scout_request` | 新建 `requester.py`，改 `tools/discover.py` |
| 3 | `scout_open` 预扫描元素 | `tools/navigate.py` |

---

## 工具总数变化

| 文件 | 现 | 增 | 后 |
|------|:--:|:--:|:--:|
| navigate.py | 5 | 0 | 5 |
| observe.py | 3 | +1 (cookies) | 4 |
| act.py | 3 | 0 | 3 |
| discover.py | 7 | +1 (request) | 8 |
| scan.py | 1 | 0 | 1 |
| **合计** | **19** | **+2** | **21** |

新增文件：`src/web_scout/requester.py`

---

## 4. SessionPage API 参考

> 来源：https://www.drissionpage.cn/SessionPage/ （DrissionPage 4.1.1.4）

### 4.1 创建

```python
from DrissionPage import SessionPage

# 最简单
page = SessionPage()

# 带配置
from DrissionPage import SessionPage, SessionOptions
so = SessionOptions(read_file=False)  # 跳过 ini 文件
page = SessionPage(session_or_options=so)
```

### 4.2 发请求

```python
# GET
page.get(url, 
    headers=dict,      # 请求头（逐项覆盖，不整体替换）
    cookies=dict,      # cookies
    params=dict,       # URL 查询参数
    timeout=float,     # 超时秒数
    allow_redirects=True,
    verify=True,       # SSL 验证
    proxies=dict,      # {'http': '...', 'https': '...'}
    retry=3,           # 重试次数
    interval=2,        # 重试间隔秒
)

# POST
page.post(url, headers=dict, cookies=dict, params=dict,
    data=dict,          # form 数据
    json=dict,          # JSON 数据（自动设 Content-Type）
    **kwargs)

# 其他方法（PUT/DELETE/PATCH/HEAD/OPTIONS）
page.session.request('PUT', url, json=data, headers=...)

# 不返回 Response，结果从 page 属性读
```

### 4.3 获取响应

```python
page.url          # str — 最终 URL（跟随重定向后）
page.title        # str — 页面标题
page.html         # str — 完整 HTML
page.json         # dict — JSON 解析结果
page.raw_data     # bytes — 原始响应体
page.user_agent   # str — 当前 UA
page.response     # Response — 原生 requests.Response 对象
page.response.status_code
page.response.headers

# 运行参数
page.timeout      # 超时（默认 10 秒）
page.retry_times  # 重试次数（默认 3）
page.retry_interval  # 重试间隔（默认 2 秒）
```

### 4.4 Cookie 操作

```python
# 读 cookie
page.cookies()                        # CookiesList（当前域名，name/value/domain）
page.cookies(all_domains=True)        # 所有域名
page.cookies(all_info=True)           # 完整信息（含 path/httpOnly/secure/expires）

# CookiesList 转换
page.cookies().as_dict()   # {name1: value1, name2: value2}
page.cookies().as_str()    # "name1=value1; name2=value2"
page.cookies().as_json()   # JSON 字符串

# 写 cookie
page.set.cookies(cookies)   # 支持多种格式：
    # list: [{'name':'a','value':'1'}, ...]
    # dict: {'a':'1', 'b':'2', 'domain':'example.com'}
    # str:  'a=1; b=2; domain=example.com; ...'
    # CookieJar 对象

# 清除/删除
page.set.cookies.clear()        # 清空所有
page.set.cookies.remove('name') # 删除指定
```

### 4.5 Headers 设置

```python
page.set.headers(dict_or_str)   # 整体设置（覆盖）
page.set.header('name', 'val')  # 单项设置
page.set.user_agent('...')      # 设置 UA
```

### 4.6 其他运行时设置

```python
page.set.retry_times(5)         # 重试次数
page.set.retry_interval(3.0)    # 重试间隔
page.set.timeout(20)            # 超时秒数
page.set.encoding('gb2312')     # 编码
page.set.proxies('http://...')  # 代理
page.set.verify(False)          # 关闭 SSL 验证
page.set.params({'k': 'v'})     # 默认查询参数
```

### 4.7 SessionOptions（启动配置）

```python
from DrissionPage import SessionPage, SessionOptions

so = SessionOptions(read_file=False)  # 不用 ini 文件
so.set_retry(5)
so.set_headers({'User-Agent': '...'})
so.set_a_header('Accept', 'application/json')
so.set_cookies(cookies)
so.set_timeout(15)
so.set_proxies('http://127.0.0.1:1080')
page = SessionPage(session_or_options=so)
```

### 4.8 关键：从浏览器 Tab 同步 Cookie 到 SessionPage

```python
# 从当前 Tab 获取 cookie
tab = state._browser.get_current_tab()
cookies_list = tab.cookies(all_domains=False, all_info=False)
# cookies_list 是 [{'name': '...', 'value': '...', 'domain': '...'}, ...]

# 转换为 dict 格式
cookies_dict = {c['name']: c['value'] for c in cookies_list}
# 或保留下 str 格式
cookies_str = '; '.join(f"{c['name']}={c['value']}" for c in cookies_list)

# 灌入 SessionPage
page.set.cookies(cookies_dict)
```

### 4.9 元素查找（非核心，但可用）

```python
page.ele('tag:div@class=item')         # 找第一个
page.eles('tag:a')                      # 找所有
page.ele('#id')                         # CSS 选择器
page.ele('@name=value')                 # 属性匹配
page.ele('tag:div@text()=关键词')       # 文本匹配

# 元素属性
ele.html / ele.inner_html / ele.tag / ele.text / ele.raw_text
ele.attrs / ele.attr('href') / ele.link
ele.xpath / ele.css_selector
```

---

## 5. 开发注意事项

### requester.py 需要处理的情况

| 情况 | 处理 |
|------|------|
| `index` 指向不存在的记录 | 返回 "API #N not found" |
| `index=0` 且 `url=""` | 返回 "Provide index or url" |
| GET 请求带 body | 转换为 POST |
| `params`/`body`/`headers` JSON 解析失败 | 返回具体错误提示 |
| 请求超时（SessionPage 默认 10s） | 捕获异常，返回 "Request timeout" |
| SSL 错误 | 提示可用 `verify=False` 关闭验证 |
| 非 2xx 状态码 | 仍然返回响应，标注状态码 |
| Cookie 获取失败（浏览器未启动） | 降级为无 cookie 发送，提示 "No cookies synced" |

### 响应体截断策略

- 默认截取前 3000 字符
- 如果是 JSON，尝试格式化后再截断
- 标注 "... (truncated, total XXXX chars)"

---

## 6. 加速方案

> 来源：https://www.drissionpage.cn/advance/accelerate/

### SessionPage 天然快

`SessionPage` 基于 requests 库，收发纯 HTTP 请求，不走浏览器渲染，本身就是最快的方案。`scout_request` 用 SessionPage 发请求，无需额外加速。

### ChromiumTab 加速：`s_eles()`（浏览器模式专用）

在 ChromiumTab（浏览器控制模式）中查找元素时，`eles()` 操作动态 DOM，耗时高（示例：163.com 取 1613 个链接，`eles()` 需 4 秒）。改用 `s_eles()` 将页面转为**静态副本**再查，耗时降至 0.28 秒（14 倍加速）。

```python
# 慢：操作动态元素
links = tab('t:body').eles('t:a')   # 4 秒

# 快：先转静态再查
links = tab('t:body').s_eles('t:a')  # 0.28 秒
```

**对我们的影响**：实测 B站搜索页扫描常见控件，JS `textContent||placeholder` 0.003s，`s_eles()+@@text()` 0.01s，JS 更快且覆盖 input placeholder。决定用 JS 方案。

**注意**：一个页面只用一次 `s_ele()`，在高层级容器上调用，然后在副本中查找子元素。多次调用会因资源消耗导致不稳定。
