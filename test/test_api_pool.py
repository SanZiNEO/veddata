"""验证 API 按 tab_id 隔离 — 完全模拟 scout_open 真实流程。

流程:
  1. 先监听, 再 browser.open(搜索页)  → 捕获 tab_A 初始 API
  2. browser.open(番剧页) 创建新标签页 → 在新标签页监听 → tab_B API
  3. browser.open(首页)   创建新标签页 → 在新标签页监听 → tab_C API
  4. 切回 tab_A (搜索页) → 输入 python + 回车 → 新 API
  5. 验证新 API 的 tab_id 是 tab_A 的，不是别的
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from web_scout import state
from web_scout.browser import BrowserSession
from web_scout.monitor import NetworkMonitor

PASS = 0
FAIL = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS [{label}]")
    else:
        FAIL += 1
        print(f"  FAIL [{label}] {detail}")


def drain(monitor, timeout=6.0):
    """Drain monitor, return raw packets with tab_id."""
    new_pkts = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        pkt = monitor.tab.listen.wait(timeout=0.5)
        if not pkt:
            break
        if monitor.filter_and_store(pkt):
            new_pkts.append({
                "tab_id": getattr(pkt, "tab_id", None),
                "method": pkt.method,
                "path": pkt.url.split("?")[0],
            })
    return new_pkts


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


# ── 清理 ─────────────────────────────────────────────────
if state._browser:
    state._browser.close()
    state._browser = None

browser = BrowserSession()
state._browser = browser


# ═══════════════════════════════════════════════════════════
# 1: 搜索页 — 先监听再 browser.open
# ═══════════════════════════════════════════════════════════
print("=== 1: 搜索页 ===")

tab = browser.get_current_tab()
m_a = NetworkMonitor(tab)
m_a.start()

browser.open("https://search.bilibili.com/all?keyword=spss")
time.sleep(3)

pkts_a = drain(m_a, timeout=8.0)
check("搜索页有 API", len(pkts_a) > 0, f"got {len(pkts_a)}")

tid_a = tab.tab_id if pkts_a else ""
if pkts_a:
    tid_a = pkts_a[0]["tab_id"] or tab.tab_id
print(f"  tab_id = {tid_a[:8]}  |  API: {len(pkts_a)} 条")


# ═══════════════════════════════════════════════════════════
# 2: 番剧页 — 新建空白标签页 → 先监听 → 再导航
# ═══════════════════════════════════════════════════════════
print("\n=== 2: 番剧页 ===")

browser._ensure_browser()
tab2 = browser._browser.new_tab()            # 建空白页
tid_b = tab2.tab_id
m_b = NetworkMonitor(tab2)
m_b.start()                                   # 先监听
tab2.get("https://www.bilibili.com/anime")    # 再导航
time.sleep(3)

pkts_b = drain(m_b, timeout=8.0)
check("番剧页有 API", len(pkts_b) > 0, f"got {len(pkts_b)}")
print(f"  tab_id = {tid_b[:8]}  |  API: {len(pkts_b)} 条")


# ═══════════════════════════════════════════════════════════
# 3: 首页 — 同上
# ═══════════════════════════════════════════════════════════
print("\n=== 3: 首页 ===")

tab3 = browser._browser.new_tab()
tid_c = tab3.tab_id
m_c = NetworkMonitor(tab3)
m_c.start()
tab3.get("https://www.bilibili.com")
time.sleep(3)

pkts_c = drain(m_c, timeout=8.0)
check("首页有 API", len(pkts_c) > 0, f"got {len(pkts_c)}")
print(f"  tab_id = {tid_c[:8]}  |  API: {len(pkts_c)} 条")


# ═══════════════════════════════════════════════════════════
# 验证: tab_id 互斥
# ═══════════════════════════════════════════════════════════
print("\n=== 验证: tab_id 互斥 ===")

ids_a = {p["tab_id"] for p in pkts_a if p["tab_id"]}
ids_b = {p["tab_id"] for p in pkts_b if p["tab_id"]}
ids_c = {p["tab_id"] for p in pkts_c if p["tab_id"]}

all_ids = ids_a | ids_b | ids_c
check("三个 tab_id 各不相同", len(all_ids) == 3, f"got {len(all_ids)}: {all_ids}")
print(f"  搜索页: {list(ids_a)[0][:8]}")
print(f"  番剧页: {list(ids_b)[0][:8]}")
print(f"  首页  : {list(ids_c)[0][:8]}")


# ═══════════════════════════════════════════════════════════
# 4: 切回搜索页 → 交互 → 验证 API 归入 tab_A
# ═══════════════════════════════════════════════════════════
print("\n=== 4: 切回搜索页 + 输入 python ===")

# 直接在搜索页 tab 上交互（listener 一直挂在 m_a 上）
search_input = find_el_by_text(tab, "输入关键字搜索", "input,textarea")
if search_input:
    search_input.click()
    time.sleep(0.3)
    search_input.clear()
    search_input.input("python")
    tab.actions.key_down('ENTER').key_up('ENTER')
    time.sleep(2)

    pkts_new = drain(m_a, timeout=6.0)
    check("交互产生新 API", len(pkts_new) > 0, f"got {len(pkts_new)}")

    tid_a_val = list(ids_a)[0]
    wrong = [p for p in pkts_new if p["tab_id"] != tid_a_val]
    check("新 API 全部归入搜索页 tab_id", len(wrong) == 0,
          f"{len(wrong)} 条 tab_id 不对: {wrong[:3]}")

    print(f"  交互 API: {len(pkts_new)} 条")
    for p in pkts_new[:5]:
        print(f"    [{p['method']}] {p['path'][:70]}  tab_id={p['tab_id'][:8]}")
    if len(pkts_new) > 5:
        print(f"    ... and {len(pkts_new) - 5} more")
else:
    check("找到搜索框", False, "搜索框未找到")


# ═══════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════
print(f"\n{'='*30}")
print(f"  PASS: {PASS}  FAIL: {FAIL}")
print(f"{'='*30}")
sys.exit(0 if FAIL == 0 else 1)
