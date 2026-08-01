"""Login detection module — cookie-based login state detection.

通用规则（对任意网站生效）:
  1. cookie name set 发生变化（新增/删除）→ 登录
  2. ≥2 个 cookie 的值同时变化 → 登录（过滤单 cookie 轮换噪声）
"""

import asyncio
import json


async def _cookie_snapshot(page) -> str:
    """Serialize cookies sorted by name for stable comparison."""
    try:
        c = await page.context.cookies()
        return json.dumps(sorted(c, key=lambda x: x["name"]), ensure_ascii=False)
    except Exception:
        return ""


def _is_login(before: str, after: str) -> bool:
    """Compare two cookie snapshots, return True if login is detected.

    Rule 1: cookie name set changed → login.
    Rule 2: ≥2 values changed at the same time → login.
    """
    if not before or not after or before == after:
        return False

    b_list = json.loads(before)
    a_list = json.loads(after)

    b_names = {c["name"] for c in b_list}
    a_names = {c["name"] for c in a_list}

    # Rule 1: name set changed → login
    if b_names != a_names:
        return True

    # Rule 2: ≥2 values changed at the same time → login
    b_map = {c["name"]: c["value"] for c in b_list}
    a_map = {c["name"]: c["value"] for c in a_list}
    changed = sum(1 for n in a_names if b_map.get(n) != a_map.get(n))

    return changed >= 2


class LoginDetector:
    """Detect login by polling cookies, wait for manual user login."""

    def __init__(self, page):
        self.page = page
        self._snapshot: str = ""

    async def take_snapshot(self):
        """Store current cookies as login-detection baseline."""
        self._snapshot = await _cookie_snapshot(self.page)

    async def wait_for_login(self, timeout: int = 300) -> bool:
        """Wait for the user to manually log in.

        Polls cookies every 0.5s; returns True when login detected,
        False on timeout.  Calls take_snapshot() at start.
        """
        await self.take_snapshot()
        if not self._snapshot:
            await asyncio.sleep(1)
            await self.take_snapshot()

        check_interval = 0.5
        elapsed = 0.0

        while elapsed < timeout:
            await asyncio.sleep(check_interval)
            elapsed += check_interval
            current = await _cookie_snapshot(self.page)

            if _is_login(self._snapshot, current):
                print(f"Login detected ({elapsed:.0f}s)")
                await self._handle_verify()
                await asyncio.sleep(3)
                try:
                    await self.page.reload()
                except Exception:
                    pass
                return True

            if elapsed % 10 < check_interval:
                print(f"  Waiting for login... ({int(elapsed)}s)")

        return False

    async def _handle_verify(self):
        """Wait for any verification popup to be manually resolved."""
        verify_selectors = [
            ".nc_wrapper", ".g-recaptcha", ".h-captcha", ".cf-turnstile",
            ".geetest_captcha",
            "text=请按住滑块拖动到最右边", "text=请向右滑动验证",
            "text=请通过验证", "text=请选择最符合描述的两张图片",
            "text=请选择包含", "text=请选择图中",
            "text=确认你不是机器人", "text=我不是機械人",
            "text=我不是机器人", "text=I am not a robot",
            "text=I'm not a robot", "text=I am human",
            "text=Verify you are human", "text=Please verify",
            "text=Complete the captcha", "text=拖动滑块",
            "text=请拖动滑块到最右边", "text=请完成验证",
            "text=请先完成验证", "text=验证码",
            "text=请输入验证码", "text=请输入下图中的字符",
            "text=请输入图片验证码", "text=点击验证",
            "text=行为验证",
        ]
        while True:
            triggered = False
            for sel in verify_selectors:
                try:
                    if sel.startswith("text="):
                        locator = self.page.get_by_text(sel[5:]).first
                    else:
                        locator = self.page.locator(sel).first
                    if await locator.is_visible(timeout=1000):
                        triggered = True
                        break
                except Exception:
                    continue
            if not triggered:
                break
            print("Security verification detected, please complete in browser...")
            await asyncio.sleep(2)
