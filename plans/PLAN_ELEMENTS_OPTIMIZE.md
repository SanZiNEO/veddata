# scout_elements — 容器发现 + 常见元素算法（v3）

> **先监听, 再导航**：DrissionPage 的 `listen.start()` 必须在触发请求的动作之前调用，否则该动作产生的数据包无法捕获。`scout_elements` 本身是只读扫描，不触发请求，但配合 `scout_act` 使用时需遵循此原则。

## 1. 当前代码方案（`dom.py`）

### list_elements() — 交互元素发现

```
querySelectorAll('a, button, input, select, [onclick], [role=button], [role=tab], [role=link]')
  → 过滤 display:none / visibility:hidden
  → 过滤 nav/header/footer 内的导航噪音
  → 去重（同一 tag+text 组合只保留一个）
  → 最多 30 个
```

无 H1-H3 加权，无文本长度评分。纯元素类型扫描。

### find_containers() — DOM 容器发现

```
① 扫所有带 class 的元素 → 按 "parent_selector → child_selector" 分组计数
② 阈值 ≥3 → 排候选列表（按 count 降序）
③ 对前 20 个候选 → 逐一提字段（_extract_container_fields_tab）
④ 评分: count × (avg_text_len + 1) + len(fields) × 5
⑤ 去重 → 取 top 5
```

**问题**：
- 计频时不检查 `display:none`——骨架占位和隐藏弹窗被计数
- 无 layout class 过滤——section/wrapper/main 等布局壳混入
- 评分只看 count 和字段数，不看文本类型（H 标签 vs span）
- 无常见元素（搜索框、翻页、登录）发现能力

---

## 2. v3 优化方案（11 站验证通过）

### 输出格式（三部分）

```
=== Clickable Elements ===
  [1] a "首页" -> //www.bilibili.com
  ...

=== DOM Containers ===
  [1] .h3.bili-video-card__info--tit[] x30 → title
  ...

=== Common Actions ===
  [搜索] input input.search-input-el "输入关键字搜索"
  [搜索] button button.vui_button "搜索"
  [下一页] button button.vui_button "下一页"
  ...
```

---

### Part 1: `list_elements()` — 不变

保持现有 `dom.py` 中的代码，无改动。

---

### Part 2: `find_containers_v3()` — 三处核心改动

#### 2.1 计频时过滤无效节点（源头拦截）

在 JS 计频循环中增加三道检查，**不计数**以下节点：

```javascript
var style = window.getComputedStyle(el);
if (style.display === 'none' || style.visibility === 'hidden') continue;  // ① 隐藏元素
var rect = el.getBoundingClientRect();
if (rect.width < 1 || rect.height < 1) continue;                           // ② 零尺寸
var ccls = parts[0];
if (LAYOUT[ccls]) continue;  // ③ layout class 黑名单
```

**LAYOUT 黑名单**（15 词）：`section, wrapper, main, side, body, row, col, container, grid, layout, content, inner, outer, header, footer`

**效果**：骨架卡片（`bili-video-card__skeleton`）、隐藏弹窗（`bili-video-card__no-interest`）、布局壳在源头就不计数。

#### 2.2 文本质量评分

旧：`score = count × (avg_text_len + 1) + len(fields) × 5`

新：`score = count × avgTextLen × headingBonus × (1 + linkRatio)`

| 因子 | 作用 |
|------|------|
| `count` | 出现次数 |
| `avgTextLen` | 平均文本长度 |
| `headingBonus` | H1-H3 = 2，其他 = 1 |
| `linkRatio` | a 标签密度 |

#### 2.3 字段提取优先文本标签

```javascript
if (tagName.match(/h[1-4]/)) name = 'title';
else { /* 按 class 名推断字段名 */ }
```

---

### Part 3: `find_common_actions()` — 新增

两层过滤：文本关键词匹配 → 语义命名过滤。

#### Step 1: 关键词匹配（纯文本）

| 关键词 | 目标 tag | 匹配来源 |
|--------|---------|---------|
| 搜索 | input,button,a | textContent / placeholder / aria-label / title / value |
| 下一页 | a,button | 同上 |
| 上一页 | a,button | 同上 |
| 登录 | a,button | 同上 |
| 注册 | a,button | 同上 |
| 排序 | button,a | 同上 |
| 筛选 | button,a | 同上 |
| 提交 | button,a | 同上 |
| 换一换 | a,button | 同上 |
| 刷新 | a,button | 同上 |
| 加载更多 | a,button | 同上 |

**不匹配 class 名**（网站 class 命名不规范，易误判）。

匹配来源顺序：`textContent → placeholder → ariaLabel → title → value`

#### Step 2: 语义命名过滤

对 Step 1 的候选，检查**自身 class + 父级 class + 祖父级 class**：

| 标签组 | 通过条件 |
|--------|---------|
| 搜索 | `<input>` 标签 **或** class 含 `search/searchbar/query/find/srh/keyword/q` |
| 下一页/上一页 | 文本 < 10 字 **或** class 含 `page/pager/btn/button/next/prev/nav` |
| 登录/注册 | 文本 < 10 字 **或** class 含 `login/register/auth/account/user/sign/btn` |
| 排序/筛选 | 文本 < 10 字 **或** class 含 `sort/filter/order/btn/tab` |
| 提交 | 文本 < 10 字 **或** class 含 `btn/button/submit` |
| 换一换/刷新/加载更多 | 文本 < 15 字 **或** class 含 `refresh/reload/btn` |

#### 去重策略

```javascript
var key = label + ':' + text + ':' + tag;  // 不用 CSS selector 去重（同 class 误判）
```

#### 循环限制

无循环上限（`i < els.length`，不用 `i < 100`）。大页面按钮多时已修复。

---

## 3. 11 站验证结果

| 站点 | 搜索 | 翻页 | 排序 | 登录 | 注册 | 容器质量 |
|------|:--:|:--:|:--:|:--:|:--:|------|
| B站搜索 | ✅ | ✅ | ✅ | — | — | 视频标题 h3 (x30) |
| 知乎热榜 | ✅ | — | — | — | — | 热搜标题 h2 (x30) |
| 豆瓣 | ✅ | — | — | — | — | 小组卡片 info (x22) |
| 京东 | —* | — | — | ✅ | ✅ | 商品卡片 more2_lk (x50) |
| 淘宝 | ✅ | — | — | ✅ | ✅ | 商品卡片 item-link (x18) |
| 网易 | ✅ | — | — | ✅ | ✅ | 新闻文章 col_l (x14) |
| CSDN | ✅ | — | — | ✅ | — | 文章卡片 article-item (x22) |
| Boss直聘 | ✅ | — | — | ✅ | ✅ | 职位卡片 job-info (x27) |
| 36氪 | —** | — | — | — | — | 文章卡片 kr-shadow (x41) |
| 微博 | ✅ | — | — | ✅ | ✅ | 微博卡片 wbpro (x6) |
| 小红书 | —*** | — | — | — | — | 笔记卡片 note-item (x30) |

\* 京东被登录墙拦截，搜索框未渲染  
\** 36氪搜索按钮纯 SVG icon，无文本  
\*** 小红书搜索使用 `<textarea>` 且按钮无文本  

10/11 站 Top 容器均为**实际数据容器**，无布局壳混入。

---

## 4. 文件改动计划

| 文件 | 改动 |
|------|------|
| `src/web_scout/dom.py` | `find_containers()` JS → v3 算法（三层过滤 + v3 评分） |
| `src/web_scout/dom.py` | `_extract_container_fields_tab()` 加 `h[1-4]` → `title` 映射 |
| `src/web_scout/dom.py` | 新增 `find_common_actions()` 方法（两层过滤） |
| `src/web_scout/dom.py` | `LAYOUT` 黑名单 15 词 |
| 评分逻辑 | `count * (avg+1) + fields*5` → `count * avgTextLen * headingBonus * (1+linkRatio)` |

`list_elements()` 不变。
