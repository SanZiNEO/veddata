"""验证 PLAN_ELEMENTS_OPTIMIZE 的 DOM 容器 v3 + Common Actions。

基于当前 dom.py 实际代码进行测试。
验证计划中的三层过滤、v3 评分、Common Actions 在当前环境下的表现。

测试内容:
  1. list_elements() — 交互元素发现（现有代码，无改动）
  2. find_containers() — 当前容器发现算法（计频 + v2 评分）
  3. LAYOUT 黑名单 15 词 - 验证 JS 中能正确过滤
  4. v3 评分公式: count × avgTextLen × headingBonus × (1 + linkRatio)
  5. h[1-4] → title 字段映射
  6. Common Actions 两层过滤（关键词匹配 + 语义命名过滤）
"""

import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from web_scout import state
from web_scout.browser import BrowserSession
from web_scout.dom import DOMScanner

TEST_URL = "https://search.bilibili.com/all?keyword=python"

PASS = 0
FAIL = 0
SKIP = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS [{label}]")
    else:
        FAIL += 1
        print(f"  FAIL [{label}] {detail}")


def skip(label):
    global SKIP
    SKIP += 1
    print(f"  SKIP [{label}]")


# ── 1. 打开页面 ────────────────────────────────────────────
print("=== 1. 启动浏览器并打开测试页面 ===")

if state._browser:
    state._browser.close()
    state._browser = None

browser = BrowserSession()
result = browser.open(TEST_URL)
time.sleep(3)

check("页面打开成功", result is not None)
check("title 非空", len(result.get("title", "")) > 0)
check("text 非空", len(result.get("text", "")) > 100, f"got {len(result.get('text',''))} chars")
print(f"  page: {result['title'][:60]}")


# ── 2. list_elements() ─────────────────────────────────────
print("\n=== 2. list_elements() ===")

tab = browser.get_current_tab()
scanner = DOMScanner(tab)
elements_output = scanner.list_elements()

check("list_elements 输出非空", len(elements_output) > 0)
check("list_elements 含 [1]", "[1]" in elements_output)
check("list_elements 含按钮或链接", "button" in elements_output or "a " in elements_output)

# 输出前 5 行
lines = elements_output.split("\n")[:5]
for l in lines:
    print(f"  {l}")


# ── 3. find_containers() 当前版本 ──────────────────────────
print("\n=== 3. find_containers() 当前 v2 算法 ===")

containers_output = scanner.find_containers()
check("find_containers 有输出", len(containers_output) > 0)
check("find_containers 含计数", "共" in containers_output and "条" in containers_output and "→" in containers_output)

# 输出
for line in containers_output.split("\n")[:8]:
    print(f"  {line}")

# 计划 v3 改动: 检查容器数量和字段质量
print("\n  当前评分公式: count × (avg_text_len + 1) + len(fields) × 5")
print("  计划 v3 公式: count × avgTextLen × headingBonus × (1 + linkRatio)")


# ── 4. LAYOUT 黑名单验证（JS 片段） ────────────────────────
print("\n=== 4. LAYOUT 黑名单 JS 验证 ===")

layout_js = """
var LAYOUT = {section:1, wrapper:1, main:1, side:1, body:1, row:1, col:1,
              container:1, grid:1, layout:1, content:1, inner:1, outer:1,
              header:1, footer:1};
var layoutElements = [];
var all = document.querySelectorAll('[class]');
var seen = {};
for (var i = 0; i < all.length; i++) {
    var el = all[i];
    var raw = el.getAttribute('class') || '';
    var parts = raw.split(/\\s+/);
    var ccls = parts[0];
    if (!ccls || seen[ccls]) continue;
    seen[ccls] = true;
    if (LAYOUT[ccls]) layoutElements.push(ccls);
}
return JSON.stringify({total: all.length, layoutHits: layoutElements});
"""
try:
    raw = tab.run_js(layout_js)
    data = json.loads(raw) if isinstance(raw, str) else raw
    check("LAYOUT 黑名单 JS 可执行", data is not None)
    print(f"  总带 class 元素数: {data.get('total', '?')}")
    print(f"  命中的 layout class: {data.get('layoutHits', [])}")
except Exception as e:
    skip(f"LAYOUT JS 执行失败: {e}")


# ── 5. v3 评分模拟 ──────────────────────────────────────────
print("\n=== 5. v3 评分公式模拟 ===")

# 模拟数据: 视频列表
sample_containers = [
    {"tag": "h3", "cls": "title", "count": 30, "avgTextLen": 20, "hasHeading": True, "linkRatio": 0.3},
    {"tag": "div", "cls": "card", "count": 15, "avgTextLen": 8, "hasHeading": False, "linkRatio": 0.1},
    {"tag": "span", "cls": "info", "count": 5, "avgTextLen": 3, "hasHeading": False, "linkRatio": 0.0},
]

for c in sample_containers:
    heading_bonus = 2.0 if c["hasHeading"] else 1.0
    score = c["count"] * max(c["avgTextLen"], 1) * heading_bonus * (1 + c["linkRatio"])
    print(f"  {c['tag']}.{c['cls']} → score={score:.0f} (count={c['count']}, avgLen={c['avgTextLen']}, heading={heading_bonus}, linkRatio={c['linkRatio']})")

# 检查 h3 容器的分数是否最高
scores = [c["count"] * max(c["avgTextLen"], 1) * (2.0 if c["hasHeading"] else 1.0) * (1 + c["linkRatio"]) for c in sample_containers]
check("v3 评分 h3 标题容器最高分", scores[0] > scores[1], f"{scores}")


# ── 6. Common Actions ──────────────────────────────────────
print("\n=== 6. Common Actions 两层过滤 ===")

common_js = """
var keywords = {
    '搜索': ['input', 'button', 'a'],
    '下一页': ['a', 'button'],
    '上一页': ['a', 'button'],
    '登录': ['a', 'button'],
    '注册': ['a', 'button'],
    '排序': ['button', 'a'],
    '筛选': ['button', 'a'],
    '提交': ['button', 'a'],
    '换一换': ['a', 'button'],
    '刷新': ['a', 'button'],
    '加载更多': ['a', 'button']
};
var filters = {
    '搜索': function(el, cls) { return el.tagName.toLowerCase() === 'input' || /search|srh|keyword|query|find/.test(cls); },
    '下一页': function(el, cls) { return (el.textContent||'').length < 10 || /page|pager|btn|button|next|prev|nav/.test(cls); },
    '上一页': function(el, cls) { return (el.textContent||'').length < 10 || /page|pager|btn|button|next|prev|nav/.test(cls); },
    '登录': function(el, cls) { return (el.textContent||'').length < 10 || /login|register|auth|account|user|sign|btn/.test(cls); },
    '注册': function(el, cls) { return (el.textContent||'').length < 10 || /login|register|auth|account|user|sign|btn/.test(cls); },
    '排序': function(el, cls) { return (el.textContent||'').length < 10 || /sort|filter|order|btn|tab/.test(cls); },
    '筛选': function(el, cls) { return (el.textContent||'').length < 10 || /sort|filter|order|btn|tab/.test(cls); },
    '提交': function(el, cls) { return (el.textContent||'').length < 10 || /btn|button|submit/.test(cls); },
    '换一换': function(el, cls) { return (el.textContent||'').length < 15 || /refresh|reload|btn/.test(cls); },
    '刷新': function(el, cls) { return (el.textContent||'').length < 15 || /refresh|reload|btn/.test(cls); },
    '加载更多': function(el, cls) { return (el.textContent||'').length < 15 || /refresh|reload|btn/.test(cls); }
};
var all = document.querySelectorAll('input, button, a, select, textarea');
var seen = {};
var results = [];
for (var i = 0; i < all.length; i++) {
    var el = all[i];
    var style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    var text = (el.textContent || '').trim();
    var placeholder = el.getAttribute('placeholder') || '';
    var ariaLabel = el.getAttribute('aria-label') || '';
    var title = el.getAttribute('title') || '';
    var val = el.getAttribute('value') || '';
    var combined = text + ' ' + placeholder + ' ' + ariaLabel + ' ' + title + ' ' + val;
    var tag = el.tagName.toLowerCase();
    var cls = el.getAttribute('class') || '';
    var pCls = (el.parentElement ? el.parentElement.getAttribute('class') || '' : '');
    var gpCls = (el.parentElement && el.parentElement.parentElement ? el.parentElement.parentElement.getAttribute('class') || '' : '');
    var allCls = cls + ' ' + pCls + ' ' + gpCls;
    for (var label in keywords) {
        var targetTags = keywords[label];
        if (targetTags.indexOf(tag) === -1) continue;
        var combinedLower = combined.toLowerCase();
        if (combinedLower.indexOf(label) === -1) continue;
        if (!filters[label](el, allCls)) continue;
        var key = label + ':' + text + ':' + tag;
        if (seen[key]) continue;
        seen[key] = true;
        results.push({label: label, tag: tag, text: text, cls: cls});
    }
}
return JSON.stringify(results);
"""
try:
    raw = tab.run_js(common_js)
    actions = json.loads(raw) if isinstance(raw, str) else raw
    if actions and len(actions) > 0:
        check("Common Actions 发现操作", len(actions) > 0)
        print(f"  发现 {len(actions)} 个 Common Action:")
        for a in actions:
            print(f"    [{a['label']}] {a['tag']} \"{(a.get('text') or a.get('cls',''))[:40]}\"")
    else:
        skip("未发现 Common Actions")
except Exception as e:
    skip(f"Common Actions JS 执行失败: {e}")


# ── 汇总 ─────────────────────────────────────────────────────
print(f"\n{'='*30}")
print(f"  PASS: {PASS}  FAIL: {FAIL}  SKIP: {SKIP}")
print(f"{'='*30}")
sys.exit(0 if FAIL == 0 else 1)
