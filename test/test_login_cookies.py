"""登录态检测测试 — 全量 JSON 字符串对比，含每次变动详情。

登录后按 Enter 停止，输出检测结论。
"""

import sys
import os
import json
import time
from datetime import datetime
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from web_scout import state
from web_scout.browser import BrowserSession

SITES = [
    "https://www.xiaohongshu.com/explore",
]


def cookie_snapshot(tab) -> str:
    c = tab.cookies(all_domains=False, all_info=False)
    return json.dumps(sorted(c, key=lambda x: x["name"]), ensure_ascii=False)


def test_site(url: str):
    print(f"\n{'='*60}")
    print(f"  测试: {url}")
    print(f"{'='*60}")

    if state._browser:
        state._browser.close()
        state._browser = None

    browser = BrowserSession()
    state._browser = browser

    tab = browser.get_current_tab()
    browser.open(url)
    time.sleep(4)

    s1 = cookie_snapshot(tab)
    time.sleep(2)
    s2 = cookie_snapshot(tab)

    if s1 == s2:
        baseline = s1
        baseline_n = len(json.loads(s1))
        baseline_b = len(s1.encode("utf-8"))
        print(f"  初始 cookie 稳定: {baseline_n} 个, {baseline_b} bytes")
    else:
        baseline = s2
        baseline_n = len(json.loads(s2))
        baseline_b = len(s2.encode("utf-8"))
        print(f"  初始 cookie 不稳定，以第二次为 baseline: {baseline_n} 个, {baseline_b} bytes")

    print(f"\n  轮询中... 登录后按 Enter 停止")
    enter_pressed = threading.Event()
    def wait_enter():
        input()
        enter_pressed.set()
    threading.Thread(target=wait_enter, daemon=True).start()

    change_log = []
    cycle = 0
    baseline_list = json.loads(baseline)
    while not enter_pressed.is_set():
        time.sleep(1)
        cycle += 1
        cur = cookie_snapshot(tab)
        if cur != baseline:
            ts = datetime.now().strftime('%H:%M:%S')
            cur_list = json.loads(cur)
            cur_map = {c["name"]: c["value"] for c in cur_list}
            bl_map = {c["name"]: c["value"] for c in baseline_list}
            cur_names = set(cur_map.keys())
            bl_names = set(bl_map.keys())

            added = cur_names - bl_names
            removed = bl_names - cur_names
            changed = {n for n in (cur_names & bl_names) if cur_map[n] != bl_map[n]}

            cur_n = len(cur_list)
            print(f"\n  [{ts}] 第{cycle}s — 变化 ({cur_n}个):")

            if added:
                for n in sorted(added):
                    print(f"    [+新增] {n:<25} = {cur_map[n][:50]}")
            if removed:
                for n in sorted(removed):
                    print(f"    [-删除] {n}")
            if changed:
                for n in sorted(changed):
                    print(f"    [~变更] {n:<25}  {bl_map[n][:40]}  →  {cur_map[n][:40]}")

            change_log.append({
                "cycle": cycle, "ts": ts,
                "added": sorted(added) if added else [],
                "removed": sorted(removed) if removed else [],
                "changed": sorted(changed) if changed else [],
            })
            baseline = cur
            baseline_list = cur_list

    # 分析: 从 change_log 里找第一次"有意义"的变化
    login_signal = None
    for e in change_log:
        has_new_name = len(e["added"]) > 0 or len(e["removed"]) > 0
        has_multi_value = len(e["changed"]) >= 2
        if has_new_name or has_multi_value:
            login_signal = e
            break

    print(f"\n  → 停止（{cycle}秒，共 {len(change_log)} 次变化）")
    if not change_log:
        print("  cookie 无变化")
    elif login_signal:
        print(f"  登录检测触发: 第{login_signal['cycle']}秒 ({login_signal['ts']})")
        if login_signal["added"]:
            print(f"    条件: 新增 cookie name — {', '.join(login_signal['added'])}")
        elif login_signal["removed"]:
            print(f"    条件: 删除 cookie name — {', '.join(login_signal['removed'])}")
        else:
            print(f"    条件: ≥2 个 cookie 同时变更值 — {', '.join(login_signal['changed'][:4])}")
        noise = [e for e in change_log if e != login_signal]
        if noise:
            print(f"    之前噪声: {len(noise)} 次单 cookie 值变化（会被规则过滤）")
    else:
        print("  无有效登录信号（仅噪声）")


for site in SITES:
    test_site(site)

print(f"\n{'='*60}")
print("  全部测试完成")
