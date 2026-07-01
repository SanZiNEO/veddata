# 002: 文本提取优化 — trafilatura 主方案 + re.sub 兜底

> **来源**: ROADMAP.md 已知问题 #2 + 规划中 "fetch 文本提取优化"
> **优先级**: P1（提升输出质量，独立于 #0）
> **影响范围**: `browser.py` — `get_text()` · `pyproject.toml` — 新增依赖

---

## 一、问题诊断

当前 `browser.py:63-127` 的 `get_text()` 使用手工 `re.sub` 链处理 HTML：

```python
# browser.py:63-127 (现状)
def get_text(self) -> str:
    html = self.tab.html
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, ...)  # 去 script
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, ...)    # 去 style
    html = re.sub(r'<nav[^>]*>.*?</nav>', '', html, ...)        # 去 nav
    html = re.sub(r'<header[^>]*>.*?</header>', '', html, ...)  # 去 header
    html = re.sub(r'<footer[^>]*>.*?</footer>', '', html, ...)  # 去 footer
    html = re.sub(r'<noscript[^>]*>.*?</noscript>', '', html, ...)
    html = re.sub(r'<svg[^>]*>.*?</svg>', '', html, ...)
    text = re.sub(r'<[^>]+>', ' ', html)  # 裸去所有标签
    ...
```

**缺陷**:

| 问题 | 示例 | 影响 |
|------|------|------|
| `nav/header/footer` 去不干净 | `<div class="footer">`、`<aside>`、语义化标签以外的导航 | 豆瓣/淘宝 残留导航文本 |
| 裸 `re.sub` 破坏 Markdown 结构 | 标题 `<h2>` 变成纯文本，链接/列表丢失 | AI 无法理解页面层级 |
| 无正文识别 | 把侧边栏、广告文本一并提取 | 噪音干扰 AI 判断 |
| CSS `class` 命名的 footer/nav 无法识别 | `<div class="site-footer">` 包含完整页脚文本 | 大量垃圾文本 |
| `<aside>`、`<article>` 之外的噪声块 | 搜索推荐词、热门标签、相关阅读混入正文 | 干扰关键词提取 |

验证方法：`scout_open("https://movie.douban.com/topic/")` 后看文本尾部是否残留导航链接。

---

## 二、候选方案对比

### trafilatura（Apache 2.0，6216⭐，ScrapingHub 基准 #1）

**API**:
```python
from trafilatura import extract
result = extract(html, output_format='markdown', include_tables=True, include_links=False)
```

| 维度 | 评价 |
|------|------|
| 正文提取 | 自动识别 `<article>`/`<main>` + 语义算法剥离导航/页脚/广告 |
| Markdown 输出 | 保留标题层级、列表、引用块、粗斜体、换行 |
| 元数据 | 可附带 title/author/date（`with_metadata=True`） |
| 中文支持 | 算法基于结构而非语言，中文页面同样有效（实测 OK） |
| 性能 | 中等（LXML 解析 + DOM 遍历），单页 ~50-200ms |
| 缺陷 | 对 SPA 页面（文本极少）或纯工具页可能返回 `None`；对表格页可能误判 |
| 依赖 | `pip install trafilatura`（约 5MB incl LXML） |

### html2text（GPLv3，2165⭐）

**API**:
```python
import html2text
h = html2text.HTML2Text()
h.body_width = 0
h.ignore_links = False
h.ignore_images = False
result = h.handle(html)
```

| 维度 | 评价 |
|------|------|
| 正文提取 | **不做**正文提取 — 把全部 HTML 转为 Markdown |
| 结构保留 | 忠实地转换标题/链接/列表/表格/图片 |
| 噪声控制 | 无，nav/footer/广告全部保留 |
| 性能 | 极快，无需 LXML，~5ms |
| 依赖 | `pip install html2text`（<100KB） |

### 结论

| 策略 | 适用场景 |
|------|---------|
| **trafilatura** 为主 | 正文型页面（文章、产品页、论坛帖子）— 拿走正文，去掉噪声 |
| **html2text** 不采用 | 不做正文提取，nav/footer 全保留，问题与现状相同 |
| **保留 re.sub 为兜底** | trafilatura 返回 `None` 时使用；工具/登录/SPA 哑页 |

---

## 三、实现设计

### 3.1 策略流程

```
get_text()
  ├─ 1. 获取 tab.html
  ├─ 2. 调用 trafilatura.extract(html, output_format='markdown')
  ├─ 3. 如果 result is not None and len(result) > 20:
  │     └─ 返回 result（截断到 MAX_TEXT_LENGTH）
  ▼ 4. 否则 fallback 到 re.sub 方案（现有逻辑）
```

### 3.2 两个模式的 trafilatura 参数选择

鉴于 `scout_open` 用于 AI 判断页面是否可用（而非精细正文阅读），采用**快速+保守**参数：

```python
# 快速模式（默认）
extract(
    html,
    output_format='markdown',
    include_tables=True,       # 保留表格
    include_links=False,       # 不去掉链接 — 对 AI 有用
    include_images=False,      # 不去掉图片 — 减少噪音
    include_comments=False,    # 不去掉评论 — 减少输出量
    favor_precision=True,      # 宁少勿滥
)
```

**采用 `favor_precision=True` 而非 `favor_recall=True`**：因为 AI 第一步是判断页面可用性，多拿噪声比漏掉正文伤害更大。噪声文本会让 AI 误判。

**采用 `output_format='markdown'`**：Markdown 保留结构（标题 `#`、列表 `-`），AI 读起来比裸文本清晰。

### 3.3 `browser.py` 改动

```python
# browser.py — 新增 trafilatura 导入
from trafilatura import extract as trafilatura_extract

class BrowserSession:

    def get_text(self) -> str:
        """Extract page text as Markdown using trafilatura, fallback to regex."""
        html = self.tab.html

        # 主方案: trafilatura 正文提取
        max_len = int(os.environ.get("MAX_TEXT_LENGTH", "3000"))
        try:
            result = trafilatura_extract(
                html,
                output_format='markdown',
                include_tables=True,
                include_links=False,
                include_images=False,
                include_comments=False,
                favor_precision=True,
            )
            if result and len(result.strip()) > 20:
                return result[:max_len]
        except Exception:
            pass  # trafilatura 失败时静默 fallback

        # 兜底: 现有 re.sub 方案（不变）
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, ...)
        # ... 现有逻辑 ...
        return text[:max_len]
```

### 3.4 `pyproject.toml` 新增依赖

```toml
dependencies = [
    "DrissionPage>=4.1",
    "fastmcp>=2.0",
    "trafilatura>=2.0",
]
```

### 3.5 环境变量配置

新增可选环境变量 `TEXT_EXTRACTOR`，用于在 trafilatura 出问题时关闭它：

```python
# browser.py — 读取配置
_extractor = os.environ.get("TEXT_EXTRACTOR", "trafilatura")
# 如果 TEXT_EXTRACTOR="legacy"，直接走 re.sub，不调 trafilatura
```

| 值 | 行为 |
|----|------|
| `"trafilatura"`（默认）| trafilatura 主方案 + re.sub 兜底 |
| `"legacy"` | 只用 re.sub，跳过 trafilatura |

---

## 四、DrissionPage 官方文档确认

`tab.html` 属性（`get_page_info` 文档）：
> 此属性返回当前页面 html 文本。html 文本不包含 `<iframe>` 元素内容。

直接传给 `trafilatura.extract()` 即可，是标准 HTML 字符串。

---

## 五、测试要点

| 场景 | URL | 预期 |
|------|-----|------|
| 文章页 | 知乎/CSDN/博客园 | trafilatura 提取正文 Markdown，无导航/页脚残留 |
| 论坛列表 | 豆瓣话题广场 | trafilatura 可能返回 None（非文章结构）→ fallback re.sub |
| 登录页 | 各种 /login | trafilatura 可能返回短文本或 None → fallback re.sub |
| SPA 空洞页 | B 站首页（纯壳） | trafilatura 返回短文本 → 低于 20 字符 → fallback |
| 公告/停服页 | 富途公告 | trafilatura 提取正文，或 fallback |
| 中文页面 | 微博/知乎/百度 | 验证 `favor_precision` 对中文的噪声剥离效果 |
| trafilatura crash | 异常 HTML | 静默 fallback 到 re.sub，不抛异常 |
| TEXT_EXTRACTOR=legacy | 任意 | 跳过 trafilatura，直接 re.sub |

---

## 六、文件改动汇总

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/web_scout/browser.py` | 新增 trafilatura import；`get_text()` 增加主方案调用 + try/except；新增 `_extractor` 环境变量检查 | ~15 行新增 |
| `pyproject.toml` | `dependencies` 列表增加 `"trafilatura>=2.0"` | 1 行 |
