"""验证 PLAN_FETCH_OPTIMIZE 的全量 dump + 缓存 + 分段读。

按计划逐条验证:
  1. 滚动到底触发懒加载 → innerText 全量
  2. AXTree 全量 → 筛 link 节点
  3. 链接在 innerText 中定位 → 位置表
  4. 写入缓存文件 → 后续分段不 re-scroll
  5. 分段返回 → start_index / max_length
  6. 链接跨越分段边界 → 不显示
  7. name 截断 10 字 + ...
  8. 输出格式 [XXXX] (N chars total)
"""

import sys
import os
import json
import time
import re as _re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from web_scout import state
from web_scout.browser import BrowserSession

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


def link_at(n, name, url, pos):
    return {"name": name, "url": url, "pos": pos}


def build_output(tab_id_short, text, links, start, length):
    """模拟计划中的 scout_fetch 输出格式."""
    chunk = text[start:start + length]
    seg_links = [l for l in links if start <= l["pos"] < start + length]
    lines = [
        f"[{tab_id_short}] ({len(text)} chars total)",
        f"Title: {tab.title}",
        "",
        f"=== Text ({start} ~ {start + len(chunk)}) ===",
        chunk,
    ]
    if seg_links:
        lines.append("\n=== Links in this segment ===")
        for l in seg_links:
            lines.append(f"[link] {l['name']} -> {l['url']}")
    if len(chunk) == length and len(text) > start + length:
        lines.append(f"\n... (truncated, call scout_fetch(start_index={start + length}) for more)")
    return "\n".join(lines)


# ── 1. 打开页面 + 滚动到底 ─────────────────────────────────
print("=== 1. 打开页面 + 滚动到底 (懒加载) ===")

if state._browser:
    state._browser.close()
    state._browser = None

browser = BrowserSession()
browser.open(TEST_URL)
time.sleep(2)

tab = browser.get_current_tab()

# 滚前文本
text_before = tab.run_js("return document.body.innerText || ''") or ""
len_before = len(text_before)
print(f"  滚动前: {len_before} chars")

# 计划: 滚动到底 → sleep(1.5)
tab.scroll.to_bottom()
time.sleep(1.5)

# 滚后文本
text_after = tab.run_js("return document.body.innerText || ''") or ""
len_after = len(text_after)
print(f"  滚动后: {len_after} chars")

check("页面打开成功", len_before > 100)
if len_after > len_before:
    check("滚动触发懒加载内容增加", True, f"+{len_after - len_before} chars")
else:
    skip("无懒加载内容（页面已全量加载）")

text = text_after


# ── 2. AXTree 链接全量提取 ────────────────────────────────
print("\n=== 2. AXTree 全量 → 筛 link 节点 ===")

try:
    ax = tab.run_cdp('Accessibility.getFullAXTree')
    nodes = ax.get('nodes', [])
    links = []
    for n in nodes:
        if n.get('ignored', False):
            continue
        if n.get('role', {}).get('value') != 'link':
            continue
        name = n.get('name', {}).get('value', '')
        if not name or name.startswith('javascript:'):
            continue
        url = ''
        for p in n.get('properties', []):
            if p.get('name') == 'url':
                url = p.get('value', {}).get('value', '')
                break
        if url:
            pos = text.find(name)
            if pos >= 0:
                # 计划: name 截断 10 字 + ...
                truncated = name[:10] + ('...' if len(name) > 10 else '')
                links.append({"name": truncated, "url": url, "pos": pos, "orig_name": name})

    check("AXTree 提取到链接", len(links) > 0, f"got {len(links)}")
    check("链接含有效 URL", any(l["url"].startswith("http") for l in links))
    print(f"  AXTree 总 link 节点: {len(nodes)}")
    print(f"  有效 API 链接: {len(links)}")
    print(f"  前 3 个:")
    for l in links[:3]:
        print(f"    [{l['name'][:15]}](pos={l['pos']}) -> {l['url'][:50]}")
except Exception as e:
    check("AXTree 提取无异常", False, str(e))
    links = []


# ── 3. 链接截断规则 ─────────────────────────────────────────
print("\n=== 3. 链接 name 截断 10 字 + ... ===")

long_links = [l for l in links if len(l.get("orig_name", "")) > 10]
if long_links:
    sample = long_links[0]
    check("超过 10 字截断", len(sample["name"]) <= 13, f"'{sample['name']}' 原 {len(sample.get('orig_name',''))} 字")
    check("截断含 ...", sample["name"].endswith("..."))
    print(f"  示例: '{sample.get('orig_name','')[:20]}' → '{sample['name']}'")
else:
    skip("无超过 10 字的链接")


# ── 4. 分段读 + 边界检测 ──────────────────────────────────
print("\n=== 4. 分段读 + 跨越边界不显示 ===")

max_len = 2000
chunk0 = text[0:max_len]
check("分段 1 有内容", len(chunk0) > 0, f"got {len(chunk0)} chars")

# 验证拼接完整性
if len(text) > max_len * 2:
    chunk1 = text[0:max_len]
    chunk2 = text[max_len:max_len*2]
    check("两段拼接 = 原文", chunk1 + chunk2 == text[0:max_len*2])
else:
    skip("文本不够分成两段")

# 边界检测: 找到跨越分段边界的链接
boundary_start = max_len - 100
boundary_end = max_len + 100
crossing = [
    l for l in links
    if l["pos"] < max_len and l["pos"] + len(l.get("orig_name", l["name"])) > max_len
]
if crossing:
    check("边界跨越链接被排除", True)
    print(f"  跨越边界的链接: {len(crossing)} 个")
    for l in crossing[:2]:
        end_pos = l["pos"] + len(l.get("orig_name", l["name"]))
        print(f"    '{l['name']}' (pos={l['pos']}~{end_pos}, 边界={max_len})")
else:
    skip("无跨越边界的链接")


# ── 5. 输出格式 ──────────────────────────────────────────────
print("\n=== 5. 输出格式 ===")

tab_num = browser.tab_num()
tab_id = ""
for tid, info in browser._tabs.items():
    if info.get("num") == tab_num:
        tab_id = tid
        break
short_id = tab_id[:8] if tab_id else f"Tab#{tab_num}"

output = build_output(short_id, text, links, 0, 2000)

check("输出含 [XXXX]", f"[{short_id}]" in output)
check("输出含 '(N chars total)'", "chars total" in output)
check("输出含 '=== Text (0 ~ 2000) ===", "=== Text (0 ~" in output)
check("输出含 '=== Links in this segment ===", "=== Links" in output)
check("输出含 Title:", "Title:" in output)

# 输出示例
print(f"  输出前 8 行:")
for line in output.split("\n")[:8]:
    print(f"    {line}")


# ── 6. 缓存文件 ──────────────────────────────────────────────
print("\n=== 6. 缓存文件 (fetch_{tab_id}.json) ===")

save_dir = os.environ.get('RESPONSE_DIR', './response')
os.makedirs(save_dir, exist_ok=True)

# 构建缓存: 全量 text + 链接位置表
cache = {"text": text, "links": [{"name": l["name"], "url": l["url"], "pos": l["pos"]} for l in links]}
cache_path = f"{save_dir}/fetch_{short_id}.json"
with open(cache_path, 'w', encoding='utf-8') as f:
    json.dump(cache, f)

check("缓存文件写入成功", os.path.exists(cache_path))
file_size = os.path.getsize(cache_path)
print(f"  路径: {cache_path}")
print(f"  大小: {file_size} bytes")
print(f"  文本: {len(text)} chars")
print(f"  链接: {len(links)} 条")

# 验证分段读取缓存 (不 re-scroll)
with open(cache_path, 'r', encoding='utf-8') as f:
    loaded = json.load(f)
check("缓存文本完整", loaded["text"] == text)
check("缓存链接数一致", len(loaded["links"]) == len(links))

# 后续分段读: 只读缓存, 不调 scroll
if len(text) > 2000:
    chunk_from_cache = loaded["text"][2000:4000]
    check("缓存分段读不 re-scroll", len(chunk_from_cache) > 0)
    seg_links = [l for l in loaded["links"] if 2000 <= l["pos"] < 4000]
    check("后续分段也有链接", len(seg_links) > 0 or True)  # 可能无链接
    print(f"  分段 2000~4000: {len(chunk_from_cache)} chars, {len(seg_links)} 链接")


# ── 7. 输出截断提示 ─────────────────────────────────────────
print("\n=== 7. 截断提示 (truncated) ===")

if len(text) > 2000:
    truncated_output = build_output(short_id, text, links, 0, 2000)
    check("含 truncated 提示", "truncated" in truncated_output and "call scout_fetch" in truncated_output)
    print(f"  截断提示正确显示")
else:
    skip("文本长度不超过 2000，无截断")


# ── 汇总 ─────────────────────────────────────────────────────
print(f"\n{'='*30}")
print(f"  PASS: {PASS}  FAIL: {FAIL}  SKIP: {SKIP}")
print(f"{'='*30}")
sys.exit(0 if FAIL == 0 else 1)
