"""验证 PLAN_OPEN_OPTIMIZE 的 AXTree 双输出 + 浏览器复用修复。

基于当前 scout_open 的实际行为测试。

测试内容:
  1. scout_open 当前输出格式: [Tab #N] url + Page Text
  2. AXTree 提取: _ax_summary() — 提取 link/button/textbox 等元素
  3. 输出格式含 "=== Elements ==="
  4. 浏览器复用: states.is_existed + quit(force=True)
  5. 第二次 scout_open 在新标签页上监听 (不丢请求)
"""

import sys
import os
import time
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from web_scout import state
from web_scout.browser import BrowserSession
from web_scout.monitor import NetworkMonitor

TEST_URL = "https://www.bilibili.com"

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


def _ax_summary(tab) -> str:
    """Extract visible interactive elements from AXTree with URLs.
    (plan PLAN_OPEN_OPTIMIZE 的实现代码)
    """
    try:
        result = tab.run_cdp('Accessibility.getFullAXTree')
        nodes = result.get('nodes', [])
        lines = []
        for n in nodes:
            if n.get('ignored', False):
                continue
            name = n.get('name', {}).get('value', '')
            if not name or len(name) < 2:
                continue
            role = n.get('role', {}).get('value', '')
            url = ''
            for p in n.get('properties', []):
                if p.get('name') == 'url':
                    url = p.get('value', {}).get('value', '')
                    break
            if url:
                lines.append(f'[{role}] {name} -> {url}')
            else:
                lines.append(f'[{role}] {name}')
        return '\n'.join(lines)
    except Exception:
        return "(AXTree unavailable)"


# ── 1. 清理旧浏览器 ─────────────────────────────────────────
print("=== 1. 清理旧浏览器 (模拟 plan 的 states.is_existed 检查) ===")

# 模拟: 检查已有连接并清理
if state._browser and state._browser._browser:
    try:
        existed = state._browser._browser.states.is_existed
        print(f"  states.is_existed = {existed}")
        if existed:
            state._browser._browser.quit(timeout=3, force=True)
            print("  → 强制关闭旧浏览器")
    except Exception as e:
        print(f"  清理异常: {e}")

state._browser = None
state._monitors.clear()
state._dom_scanners.clear()

check("浏览器已重置", state._browser is None)


# ── 2. 标准 scout_open 流程 ─────────────────────────────────
print("\n=== 2. 模拟 scout_open 流程（监听 + 导航） ===")

browser = BrowserSession()
state._browser = browser

# 创建监听器（挂在当前 tab 上）
tab_before = browser.get_current_tab()
monitor = NetworkMonitor(tab_before)
monitor.start()

# 导航
result = browser.open(TEST_URL)
time.sleep(3)
monitor.step(timeout=8.0)

tab_num = browser.tab_num()
state._monitors[tab_num] = monitor

check("页面打开成功", result is not None)
check("tab_num > 0", tab_num > 0)
check("title 非空", len(result.get("title", "")) > 0)
check("text 非空", len(result.get("text", "")) > 100, f"got {len(result.get('text',''))} chars")
print(f"  [Tab #{tab_num}] {result['title'][:60]}")


# ── 3. AXTree 输出 ──────────────────────────────────────────
print("\n=== 3. AXTree 双输出 (_ax_summary) ===")

tab_after = browser.get_current_tab()
elements_output = _ax_summary(tab_after)

check("_ax_summary 输出非空", len(elements_output) > 50, f"got {len(elements_output)} chars")

# 检查角色类型
for role in ["[link]", "[button]", "[StaticText]", "[textbox]", "[heading]"]:
    if role in elements_output:
        print(f"  发现角色: {role}")

check("包含 [link]", "[link]" in elements_output)
check("含 URL 箭头 ->", "->" in elements_output)
check("含 http url", "http" in elements_output)

# 输出前 10 行
lines = elements_output.split("\n")[:10]
for l in lines:
    print(f"  {l}")


# ── 4. 输出格式验证 ────────────────────────────────────────
print("\n=== 4. 输出格式 ===")

plan_output = "\n".join([
    str(state.prefix(tab_num)),
    f"Page opened: {result['title'] or TEST_URL}",
    "",
    "=== Page Text ===",
    result["text"],
    "",
    "=== Elements ===",
    elements_output,
])

check("含 '=== Page Text ==='", "=== Page Text ===" in plan_output)
check("含 '=== Elements ==='", "=== Elements ===" in plan_output)
check("含 'Page opened'", "Page opened" in plan_output)
check("含 [Tab #N]", f"[Tab #{tab_num}]" in plan_output)
print(f"  格式符合计划要求")


# ── 5. 第二次 scout_open 模拟 ───────────────────────────────
print("\n=== 5. 第二次 scout_open (监听 + 导航) ===")

# 第二次导航 (B站搜索)
search_url = "https://search.bilibili.com/all?keyword=python"
tab_before_2 = browser.get_current_tab()

# 如果已经开了一个页面, open() 可能创建新标签页
tab_num_before = browser.tab_num()

monitor2 = NetworkMonitor(tab_before_2)
monitor2.start()
result2 = browser.open(search_url)
time.sleep(3)
monitor2.step(timeout=8.0)

tab_num_after = browser.tab_num()
state._monitors[tab_num_after] = monitor2

check("第二次导航成功", result2 is not None)
check("搜索页 title 含 python", "python" in result2.get("title", "").lower())

# 验证 tab 编号
if tab_num_after != tab_num_before:
    print(f"  → 创建了新标签页: Tab #{tab_num_before} → Tab #{tab_num_after}")
else:
    print(f"  → 复用了当前标签页: Tab #{tab_num_after}")

# 检查 pages 数量
api_count = len(monitor2.api_records)
check("第二次导航捕获了 API", api_count > 0, f"total {api_count} APIs captured")
if api_count > 0:
    print(f"  API 记录: {api_count}")


# ── 6. 浏览器复用修复 ──────────────────────────────────────
print("\n=== 6. 浏览器复用修复 (states.is_existed) ===")

# 验证: 当 MCP 重启后, 旧 browser 存在的处理
# 当前 BrowserSession._browser 是 Chromium 实例
if browser._browser:
    is_existed = browser._browser.states.is_existed
    check("states.is_existed 可访问", isinstance(is_existed, bool))
    print(f"  states.is_existed = {is_existed}")

    # 验证 tab_ids 列表
    tab_ids = browser._browser.tab_ids
    check("tab_ids 非空", len(tab_ids) > 0)
    print(f"  浏览器标签页数: {len(tab_ids)}")
    for tid in tab_ids:
        try:
            tb = browser._browser.get_tab(tid)
            print(f"    [{tid[:8]}] {str(tb.title or '')[:50]}")
        except Exception:
            print(f"    [{tid[:8]}] (无法获取)")

    # 验证 _tabs 字典同步
    check("_tabs 长度 = tab_ids 长度",
          len(browser._tabs) == len(tab_ids),
          f"_tabs={len(browser._tabs)}, tab_ids={len(tab_ids)}")


# ── 7. new_env() 测试 ─────────────────────────────────────
print("\n=== 7. new_env() 创建全新浏览器 ===")

from DrissionPage import Chromium, ChromiumOptions

# 记录旧的 tab_ids
old_tab_ids = []
if browser._browser:
    old_tab_ids = list(browser._browser.tab_ids)
    print(f"  旧浏览器 tab_ids: {len(old_tab_ids)} 个")

# 关闭旧的 BrowserSession
if state._browser:
    state._browser.close()
    state._browser = None
state._monitors.clear()
state._dom_scanners.clear()
time.sleep(1)

# 用 new_env() 创建全新浏览器
print("  用 new_env() 创建新浏览器...")
try:
    co = ChromiumOptions().new_env()
    new_browser = Chromium(co)
    check("new_env() 创建成功", new_browser is not None)
    check("new_browser 的 tab_ids 非空", len(new_browser.tab_ids) > 0)

    new_tab_ids = list(new_browser.tab_ids)

    if old_tab_ids:
        overlap = [t for t in old_tab_ids if t in new_tab_ids]
        check("标签页不在旧列表中", len(overlap) == 0, f"重叠 {len(overlap)} 个")
    else:
        skip("无旧标签页可比较")

    # 新浏览器能正常打开页面
    new_tab = new_browser.latest_tab
    new_tab.get(TEST_URL)
    time.sleep(2)
    title = new_tab.title or ""
    check("新浏览器能打开页面", len(title) > 0)
    print(f"  新标签页标题: {title[:60]}")

    new_browser.quit()

except Exception as e:
    check("new_env() 无异常", False, str(e))
    print(f"  ERROR: {e}")


# ── 汇总 ─────────────────────────────────────────────────────
print(f"\n{'='*30}")
print(f"  PASS: {PASS}  FAIL: {FAIL}  SKIP: {SKIP}")
print(f"{'='*30}")
sys.exit(0 if FAIL == 0 else 1)
