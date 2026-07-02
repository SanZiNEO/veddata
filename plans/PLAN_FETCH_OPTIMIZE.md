# scout_fetch 全量获取优化计划

## 目标

`scout_fetch` 从"再输出一遍 open 内容+链接列表"改为真正的全量 dump：
滚动到底 → AXTree 取全量元素 → innerText 取全量文本 → 写临时文件 → AI 分段按需读。

---

## 当前状态

```
scout_fetch(max_length, start_index)
  → innerText（和 open 一样的内容）
  → regex 扫 HTML 找 <a> 链接
  → 分块返回
```

问题：内容少（B站 741 字）、链接含 60% 导航噪音、和 open 重复。

---

## 优化方案

### 流程

```
scout_fetch(max_length=5000, start_index=0)
  1. 滚动到底部 → sleep(1.5) 等渲染
  2. innerText 全量 → 滚动后的完整页面文本
  3. AXTree 全量 → 筛出所有 link 节点（name + url）
  4. 匹配链接在 innerText 中的位置
  5. 全量文本 + 链接位置表 → 写入临时文件 {RESPONSE_DIR}/fetch_{tab}.txt
  6. 按 start_index / max_length 切段返回给 AI
```

### 输出格式

```
[Tab #1] https://www.bilibili.com/  (全量 48200 chars)
Title: 哔哩哔哩

=== Text (0 ~ 5000) ===
首页 番剧 直播 ... 实话！重庆人真心挚爱... 54.2万 ... 换一换

=== Links in this segment ===
[link] 实话！重庆人真心挚爱便... -> https://www.bilibili.com/video/BV...
[link] 半夜家里进了个贼 -> https://www.bilibili.com/video/BV...
[link] 审核了不止十年的低创鬼畜 -> https://www.bilibili.com/video/BV...

... (truncated, call scout_fetch(start_index=5000) for more)
```

### 链接处理规则

- 提取 AXTree 中所有 `role=link` 的非 ignored 节点
- `name` 为链接文本，`url` 为链接地址（从 properties 取）
- 在 innerText 中用 `str.find(name)` 定位位置
- **截断规则**：name 截断到 10 字 + `...`；如果链接文字跨越分段边界（start_index 和 start_index+max_length 分别落在文字两侧），该链接在本段不显示
- 排除纯锚点链接（`javascript:`）、空文本链接

### 临时文件

- 路径：`{RESPONSE_DIR}/fetch_{tab_number}.txt`
- 内容：全量 innerText（collapsed whitespace）+ 链接位置 JSON
- 每次调用覆盖（同一 tab），tab 关闭时清理
- 不占 AI 上下文，AI 通过 `start_index` 分段读

### 参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `max_length` | 5000 | 每段最大字符数 |
| `start_index` | 0 | 起始字符位置 |
| `tab` | 0 | 目标标签页 |

---

## 改动范围

| 文件 | 改动 |
|------|------|
| `tools/observe.py` | 重写 `scout_fetch` 函数 |

---

## 性能

| 步骤 | 耗时 |
|------|------|
| scroll 到底 | ~1s |
| innerText（全量） | ~3ms |
| AXTree 全量 | ~110ms |
| 链接匹配 + 分段 | ~10ms |
| **首次调用合计** | **~1.2s** |
| 后续分段读（不 rescroll） | ~3ms |
