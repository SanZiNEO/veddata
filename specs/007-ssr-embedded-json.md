# 007: SSR 页面内嵌 JSON 捕获 — `window.__INITIAL_STATE__`

> **来源**: ROADMAP.md 已知问题 #7（🔴 知乎实测）
> **优先级**: P0（知乎/小红书/Next.js 等大量站点数据源完全漏掉）
> **影响范围**: `monitor.py` — 新增 `capture_embedded_json()` · `server.py` — `scout_analyze()` 增加提取步骤

---

## 一、问题诊断

知乎、小红书、Next.js 等 SSR/SSG 站点将页面数据直接嵌入 HTML `<script>` 标签：

```html
<script>window.__INITIAL_STATE__ = {"topStory": {...}, "articles": [...]}</script>
<script id="__NEXT_DATA__" type="application/json">{"props": {...}}</script>
```

**当前 web-scout 三条数据路径全部漏掉**:

| 路径 | 为什么漏 |
|------|---------|
| API 监听 | 不走 XHR/Fetch — 数据在页面源码里 |
| DOM 扫描 | 忽略 `<script>` 标签内容 — 只扫 `[class]` 元素 |
| 文本提取 | 输出的 Markdown 里没有 `<script>` 内容（`get_text()` 已删 script 标签） |

**受影响的变量模式**:

| 变量名 | 用什么框架 | 典型站点 |
|--------|-----------|---------|
| `__INITIAL_STATE__` | 自研/早期 SPA | 知乎、豆瓣 |
| `__NEXT_DATA__` | Next.js | Vercel 系站点 |
| `__NUXT__` | Nuxt.js | Vue SSR 站点 |
| `window.__DATA__` | 自研 | 小红书 |
| `__PRELOADED_STATE__` | Redux SSR | 各类 React SSR |
| `__APP_DATA__` | 自研 | 少数站点 |
| `__RENDER_DATA__` | Vue SSR | 少数站点 |
| `__ASYNC_DATA__` | 自研 | 少数站点 |

> 知乎实测：首页 feed 数据全在 `__INITIAL_STATE__` 里，`scout_open + scout_analyze` 返回 `APIs: 0`，但实际页面数据丰富。

---

## 二、目标设计

### 定位

嵌入式 JSON 作为**第三种数据源**（API / DOM / Embedded JSON），与 API 记录并列但独立管理。

### 工作流

```
scout_open(url) → 文本
AI 读文本判断页面可用
scout_analyze()  → 启动 API 监听 + 扫描 DOM + 提取嵌入式 JSON
                   返回: APIs: N, DOM: M, Embedded: K
scout_list_apis()  → 列出 API + 嵌入式数据源
scout_inspect_api() → 查看详情（API 或嵌入式）
scout_export()     → 导出（API 或嵌入式）
```

### 提取策略

`tab.run_js()` 遍历 `window` 全局变量：

```javascript
(function() {
    var patterns = [
        '__INITIAL_STATE__', '__NEXT_DATA__', '__NUXT__',
        '__PRELOADED_STATE__', '__APP_DATA__', '__RENDER_DATA__',
        '__ASYNC_DATA__'
    ];
    var results = {};
    for (var i = 0; i < patterns.length; i++) {
        var key = patterns[i];
        try {
            var val = window[key];
            if (val !== undefined && val !== null) {
                results[key] = val;
            }
        } catch(e) {}
    }
    // 额外: 扫描 <script id> 标签中的 application/json
    var scripts = document.querySelectorAll('script[type="application/json"], script[type="application/ld+json"]');
    for (var j = 0; j < scripts.length; j++) {
        var s = scripts[j];
        var id = s.id || ('script_json_' + j);
        try {
            results[id] = JSON.parse(s.textContent);
        } catch(e) {}
    }
    return JSON.stringify(results);
})()
```

返回的 JSON 字符串由 Python 端解析，每个 key 变成一个"嵌入式数据源"记录。

---

## 三、实现细节

### 3.1 `monitor.py` — 新增 `capture_embedded_json()`

```python
class NetworkMonitor:

    def __init__(self, tab):
        self.tab = tab
        self.api_records: list[dict] = []
        self.embedded_records: list[dict] = []  # 新增
        self._next_id = 1

    def capture_embedded_json(self) -> int:
        """Extract embedded JSON from window globals and <script type=application/json>.

        Returns number of embedded data sources found.
        """
        self.embedded_records.clear()

        js = """
        (function() {
            var targets = [
                '__INITIAL_STATE__', '__NEXT_DATA__', '__NUXT__',
                '__PRELOADED_STATE__', '__APP_DATA__', '__RENDER_DATA__',
                '__ASYNC_DATA__'
            ];
            var results = {};
            for (var i = 0; i < targets.length; i++) {
                var key = targets[i];
                try {
                    var val = window[key];
                    if (val !== undefined && val !== null) {
                        results[key] = val;
                    }
                } catch(e) {}
            }
            var scripts = document.querySelectorAll(
                'script[type="application/json"], script[type="application/ld+json"]'
            );
            for (var j = 0; j < scripts.length; j++) {
                var s = scripts[j];
                var id = s.id || ('script_json_' + j);
                try {
                    results[id] = JSON.parse(s.textContent);
                } catch(e) {}
            }
            return JSON.stringify(results);
        })()
        """
        try:
            raw = self.tab.run_js(js)
            if not raw:
                return 0
            data = json.loads(raw)
        except (json.JSONDecodeError, Exception):
            return 0

        if not isinstance(data, dict):
            return 0

        for key, value in data.items():
            if value is None:
                continue
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, ValueError):
                    pass  # 保留原始字符串
            field_count = _leaf_count(value) if isinstance(value, (dict, list)) else 0
            self.embedded_records.append({
                "id": self._next_id,
                "source": "embedded",
                "key": key,
                "url": self.tab.url,
                "method": "SSR",
                "path": f"window.{key}",
                "count": 1,
                "request_headers": {},
                "request_params": {},
                "request_body": None,
                "response_status": 200,
                "response_body": value,
                "field_count": field_count,
            })
            self._next_id += 1

        return len(self.embedded_records)
```

### 3.2 `monitor.py` — `list_apis()` 混入嵌入式记录

```python
def list_apis(self, keyword: str | None = None) -> str:
    # 合并 API 记录 + 嵌入式记录
    all_records = self.api_records + self.embedded_records
    
    if keyword:
        # 现有过滤逻辑...
        ...
    
    if not all_records:
        return "No APIs or embedded data captured yet."
    
    lines = []
    for rec in all_records:
        method = rec["method"]
        path = rec["path"]
        count = rec["count"]
        fields = rec["field_count"]
        source = rec.get("source", "api")
        tag = "[embedded]" if source == "embedded" else ""
        lines.append(f"[{rec['id']}] {tag} {method} {path}  {count} {'times' if count > 1 else 'time'} → {fields} fields")
    return "\n".join(lines)
```

### 3.3 `monitor.py` — `get_record()` 扩展

```python
def get_record(self, api_id: int) -> dict | None:
    for rec in self.api_records:
        if rec["id"] == api_id:
            return rec
    # 新增: 也搜索嵌入式记录
    for rec in self.embedded_records:
        if rec["id"] == api_id:
            return rec
    return None
```

### 3.4 `server.py` — `scout_analyze()` 增加嵌入式提取

```python
def scout_analyze() -> str:
    global _monitor, _dom, _exporter, _browser

    if not _browser:
        return "Error: call scout_open first."
    if _login_pending:
        return "Error: call scout_wait_login() first."

    _monitor = NetworkMonitor(_browser.tab)
    _monitor.start()
    time.sleep(3)
    api_count = _monitor.wait_new(timeout=3.0)

    # 新增: 提取嵌入式 JSON
    embedded_count = _monitor.capture_embedded_json()

    _dom = DOMScanner(_browser.tab)
    _exporter = Exporter()
    containers = _dom.find_containers()
    dom_count = len(_dom.containers_cache)

    parts = [f"Analyze complete: {api_count} APIs, {dom_count} DOM containers, {embedded_count} embedded data sources."]
    if api_count > 0:
        parts.append("Use scout_list_apis() to list all captured endpoints.")
    if embedded_count > 0:
        parts.append("Embedded JSON sources (e.g. __INITIAL_STATE__) are included in scout_list_apis() output.")
    if dom_count > 0:
        parts.append("Use scout_list_elements() to list interactive elements and containers.")
    return "\n".join(parts)
```

---

## 四、现有工具的兼容性

| 工具 | 嵌入式 JSON 是否可见 | 说明 |
|------|---------------------|------|
| `scout_list_apis()` | ✅ 可见 | 显示 `[embedded]` 标签 |
| `scout_inspect_api(n)` | ✅ 可用 | `get_record()` 同时搜索两个列表 |
| `scout_export(n)` | ✅ 可用 | 导出逻辑对嵌入式记录同样工作 |
| `scout_search(keyword)` | ✅ 可用 | `list_apis(keyword)` 已合并搜索 |
| `scout_fetch_api()` | ❌ 不适用 | 自包含工具，不走嵌入式 |

---

## 五、测试要点

| 场景 | URL | 预期 |
|------|-----|------|
| 知乎首页 | `zhihu.com` | `embedded_count >= 1`，`__INITIAL_STATE__` 被捕获 |
| Next.js 站点 | 任意 Next.js 页面 | `__NEXT_DATA__` 被捕获 |
| Nuxt.js 站点 | 任意 Nuxt 页面 | `__NUXT__` 被捕获 |
| `<script type="application/json">` | 含此类标签的页面 | 对应 id 的数据被捕获 |
| `<script type="application/ld+json">` | SEO 结构数据 | JSON-LD 被捕获 |
| 无嵌入式数据 | 纯 HTML 页面 | `embedded_count = 0`，不报错 |
| 知乎 → inspect | `scout_inspect_api(n)` | 正常展示字段结构 |
| 知乎 → export | `scout_export(n)` | 正常导出 JSON |

---

## 六、文件改动汇总

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/web_scout/monitor.py` | 新增 `embedded_records` 列表；新增 `capture_embedded_json()` 方法；修改 `list_apis()` 合并两列表；修改 `get_record()` 搜索两个列表 | ~60 行 |
| `src/web_scout/server.py` | `scout_analyze()` 中增加 `capture_embedded_json()` 调用 | ~3 行 |
