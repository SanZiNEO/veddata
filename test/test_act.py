"""验证 PLAN_ACT_OPTIMIZE 的链式交互。

测试 B站搜索页的完整操作流:
  1. 打开搜索页 → Tab #1
  2. find_el_by_text 定位搜索框 + 输入 spss + 回车
  3. 点击「最多播放」排序
  4. 点击「更多筛选」
  5. 点击「30-60分钟」时长过滤
  6. 每次操作后检查 monitor 是否捕获新 API
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from web_scout import state
from web_scout.browser import BrowserSession
from web_scout.monitor import NetworkMonitor

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


# ── 辅助: 文本定位元素 ─────────────────────────────────────
def find_el_by_text(tab, text, tags="a,button,input,select,span"):
    for tag in tags.split(','):
        for el in tab.eles(f'tag:{tag}'):
            try:
                if not el.states.is_displayed:
                    continue
                combined = (
                    (el.text or '')
                    + ' ' + (el.attr('placeholder') or '')
                    + ' ' + (el.attr('aria-label') or '')
                )
                if text in combined:
                    return el
            except Exception:
                pass
    return None


# ── 1. 打开页面 ────────────────────────────────────────────
print("=== 1. 打开搜索页 ===")

if state._browser:
    state._browser.close()
    state._browser = None

browser = BrowserSession()
browser.open(TEST_URL)
time.sleep(3)

tab = browser.get_current_tab()
monitor = NetworkMonitor(tab)
monitor.start()

tab_num = browser.tab_num()
state._monitors[tab_num] = monitor
state._browser = browser

api_count = lambda: len(monitor.api_records)

check("页面打开成功", True)
print(f"  [Tab #{tab_num}] {tab.title[:60]}")
print(f"  当前 API: {api_count()}")


# ── 2. 输入搜索词 ─────────────────────────────────────────
print("\n=== 2. 搜索框输入 spss + 回车 ===")

search_input = find_el_by_text(tab, "输入关键字搜索", "input,textarea")
check("找到搜索框", search_input is not None, "未找到输入框")

if search_input:
    api_before = api_count()
    search_input.click()
    time.sleep(0.3)
    search_input.clear()
    search_input.input("spss")
    tab.actions.key_down('ENTER').key_up('ENTER')
    check("输入 spss 无异常", True)
    print(f"  Input 'spss' into search box")

    time.sleep(2)
    monitor.step(timeout=5.0)
    api_after = api_count()
    check("输入后 API 增加", api_after > api_before, f"+{api_after - api_before}")
    print(f"  API: {api_before} → {api_after}")


# ── 3. 点击排序按钮 ───────────────────────────────────────
print("\n=== 3. 点击「最多播放」排序 ===")

# 搜索后可能重新导航, 更新 tab 引用
tab = browser.get_current_tab()
api_before = api_count()

sort_btn = find_el_by_text(tab, "最多播放", "a,button,span")
check("找到「最多播放」按钮", sort_btn is not None, "未找到排序按钮")

if sort_btn:
    sort_btn.click()
    check("点击最多播放", True)
    print(f"  Clicked '最多播放'")

    time.sleep(2)
    monitor.step(timeout=5.0)
    api_after = api_count()
    check("排序后 API 增加", api_after > api_before, f"+{api_after - api_before}")
    print(f"  API: {api_before} → {api_after}")


# ── 4. 点击更多筛选 ───────────────────────────────────────
print("\n=== 4. 点击「更多筛选」 ===")

tab = browser.get_current_tab()
api_before = api_count()

more_btn = find_el_by_text(tab, "更多筛选", "a,button,span")
check("找到「更多筛选」按钮", more_btn is not None, "未找到筛选按钮")

if more_btn:
    more_btn.click()
    check("点击更多筛选", True)
    print(f"  Clicked '更多筛选'")

    time.sleep(1)
    monitor.step(timeout=3.0)
    api_after = api_count()
    print(f"  API: {api_before} → {api_after}")


# ── 5. 点击时长过滤 ───────────────────────────────────────
print("\n=== 5. 点击「30-60分钟」时长 ===")

tab = browser.get_current_tab()
api_before = api_count()

duration_btn = find_el_by_text(tab, "30-60分钟", "a,button,span")
check("找到「30-60分钟」按钮", duration_btn is not None, "未找到时长按钮")

if duration_btn:
    duration_btn.click()
    check("点击30-60分钟", True)
    print(f"  Clicked '30-60分钟'")

    time.sleep(2)
    monitor.step(timeout=5.0)
    api_after = api_count()
    check("过滤后 API 增加", api_after > api_before, f"+{api_after - api_before}")
    print(f"  API: {api_before} → {api_after}")


# ── 6. scout_click 退役检查 ───────────────────────────────
print("\n=== 6. scout_click 退役 ===")

import web_scout.server
from web_scout.tools.act import scout_click

check("scout_click 仍可导入", callable(scout_click))
print(f"  计划: scout_act('click', target=...) 替代 scout_click")


# ── 汇总 ─────────────────────────────────────────────────────
print(f"\n{'='*30}")
print(f"  PASS: {PASS}  FAIL: {FAIL}  SKIP: {SKIP}")
print(f"{'='*30}")
sys.exit(0 if FAIL == 0 else 1)
