"""验证 scout_cookies + scout_request 完整流程 (微博).

流程:
  1. 打开微博帖子页 (先监听, 再导航)
  2. 捕获评论 API: /ajax/statuses/buildComments
  3. 提取请求参数, SessionPage 重放
  4. Exporter.compact() 压缩字段结构
  5. 保存原始 JSON + 字段文档到本地
  6. cookie 验证
"""

import sys
import os
import time
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from web_scout import state
from web_scout.browser import BrowserSession
from web_scout.monitor import NetworkMonitor
from web_scout.export import Exporter

TEST_URL = "https://weibo.com/2202387347/R6EQycO7V"
COMMENT_PATH = "/ajax/statuses/buildComments"

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


# ── 清理 ─────────────────────────────────────────────────
if state._browser:
    state._browser.close()
    state._browser = None

browser = BrowserSession()
state._browser = browser

tab = browser.get_current_tab()


# ── 1. 先监听, 再导航 ────────────────────────────────────
print("=== 1. 先监听, 再导航 ===")

monitor = NetworkMonitor(tab)
monitor.start()

browser.open(TEST_URL)
time.sleep(5)

monitor.step(timeout=8.0)
check("页面加载后有 API", len(monitor.api_records) > 0, f"got {len(monitor.api_records)}")

# 查找评论 API
comment_records = [r for r in monitor.api_records if COMMENT_PATH in r["path"]]
check("发现评论 API", len(comment_records) > 0, f"got {len(comment_records)}")

target = None
for r in comment_records:
    target = r
    print(f"  [{r['method']}] {r['path']}  (status={r.get('response_status')})")
    print(f"  url: {r['url']}")
    print(f"  params: {json.dumps(r.get('request_params', {}), indent=2, ensure_ascii=False)[:300]}")

check("评论 API 状态 200", target and target.get("response_status") == 200, str(target.get("response_status") if target else "None"))


# ── 2. SessionPage 重放 ──────────────────────────────────
print("\n=== 2. SessionPage 重放 ===")

if target:
    from DrissionPage import SessionPage

    page = SessionPage()

    # 从浏览器同步 cookie
    try:
        cookies_list = tab.cookies(all_domains=False, all_info=False)
        if cookies_list:
            page.set.cookies({c['name']: c['value'] for c in cookies_list})
            print(f"  同步 cookie: {len(cookies_list)} 个")
    except Exception as e:
        print(f"  cookie 同步: {e}")

    # 从捕获记录提取基础参数
    captured_params = target.get("request_params", {})
    post_id = captured_params.get("id", "")
    post_uid = captured_params.get("uid", "")

    # 用 weiibo_ad 项目的参数格式 (is_show_bulletin=3, count=20)
    url = target["url"].split("?")[0]
    params = {
        "is_reload": 1, "id": post_id, "uid": post_uid,
        "is_show_bulletin": 3, "is_mix": 0, "count": 20,
        "fetch_level": 0, "locale": "zh-CN",
    }
    headers = {"Referer": TEST_URL, "X-Requested-With": "XMLHttpRequest"}

    # 从 cookie 获取 xsrf token → X-XSRF-TOKEN header
    try:
        ck = tab.cookies(all_domains=False, all_info=False)
        xsrf = next((c["value"] for c in ck if c["name"] == "XSRF-TOKEN"), "")
        if xsrf:
            headers["X-XSRF-TOKEN"] = xsrf
            print(f"  X-XSRF-TOKEN: {xsrf[:20]}...")
    except Exception:
        pass

    t0 = time.perf_counter()
    page.get(url, params=params, headers=headers)
    elapsed = (time.perf_counter() - t0) * 1000

    check("重放状态 200", page.response.status_code == 200, str(page.response.status_code))
    check("重放耗时 < 5s", elapsed < 5000, f"{elapsed:.0f}ms")
    check("返回 JSON", page.json is not None)

    print(f"  Status: {page.response.status_code}  |  Time: {elapsed:.0f}ms")
    if isinstance(page.json, dict):
        print(f"  JSON keys: {list(page.json.keys())}")
        ok = page.json.get("ok", 0)
        total = page.json.get("total_number", 0)
        data = page.json.get("data", [])
        max_id = page.json.get("max_id", 0)
        print(f"  ok={ok}  total={total}  data={len(data)}  max_id={max_id}")

    # ── 翻页: 用 max_id 请求下一页 ──
    if page.json and page.json.get("max_id"):
        max_id = page.json["max_id"]
        print(f"\n  翻页: max_id={max_id}")

        page2 = SessionPage()
        # 同步同一份 cookie
        try:
            ck2 = tab.cookies(all_domains=False, all_info=False)
            if ck2:
                page2.set.cookies({c['name']: c['value'] for c in ck2})
        except Exception:
            pass

        page2_params = {
            "flow": 0, "is_reload": 0, "id": post_id, "uid": post_uid,
            "is_show_bulletin": 3, "is_mix": 0, "max_id": max_id,
            "count": 20, "fetch_level": 0, "locale": "zh-CN",
        }
        t1 = time.perf_counter()
        page2.get(url, params=page2_params, headers=headers)
        elapsed2 = (time.perf_counter() - t1) * 1000

        check("翻页状态 200", page2.response.status_code == 200, str(page2.response.status_code))
        check("翻页耗时 < 5s", elapsed2 < 5000, f"{elapsed2:.0f}ms")

        data2 = page2.json.get("data", []) if page2.json else []
        max_id2 = page2.json.get("max_id", 0) if page2.json else 0
        check("翻页获取到数据", len(data2) > 0, f"got {len(data2)} 条评论")
        print(f"  Status: {page2.response.status_code}  |  Time: {elapsed2:.0f}ms")
        print(f"  data: {len(data2)} 条  |  max_id={max_id2}")


# ── 3. 字段压缩 ──────────────────────────────────────────
print("\n=== 3. 字段压缩 (Exporter.compact) ===")

if target:
    exporter = Exporter(response_dir="./response")
    field_doc = exporter.compact(target)
    check("字段文档非空", len(field_doc) > 50, f"got {len(field_doc)} chars")
    print(f"  {field_doc[:600]}")


# ── 4. 保存到本地 ─────────────────────────────────────────
print("\n=== 4. 保存到本地 ===")

if target:
    save_dir = "./response"
    os.makedirs(save_dir, exist_ok=True)

    if page and page.json:
        raw_path = f"{save_dir}/weibo_comments.json"
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(page.json, f, indent=2, ensure_ascii=False)
        check("原始 JSON 已保存", os.path.exists(raw_path))
        print(f"  原始 JSON: {raw_path}")

    export_result = exporter.export(target, format="both", output_dir=save_dir)
    check("export 非空", len(export_result) > 50)
    print(f"  export: {export_result[:200]}")
else:
    skip("无评论 API")


# ── 5. cookie ────────────────────────────────────────────
print("\n=== 5. 当前 cookie ===")

try:
    ck = tab.cookies(all_domains=False, all_info=False)
    check("有 cookie", len(ck) > 0, f"got {len(ck)}")
    for c in ck[:4]:
        print(f"    {c['name']:<20} = {str(c['value'])[:30]}  ({c['domain']})")
except Exception as e:
    check("cookie 无异常", False, str(e))


# ── 汇总 ─────────────────────────────────────────────────
print(f"\n{'='*30}")
print(f"  PASS: {PASS}  FAIL: {FAIL}  SKIP: {SKIP}")
print(f"{'='*30}")
sys.exit(0 if FAIL == 0 else 1)
