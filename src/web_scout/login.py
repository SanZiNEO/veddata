"""Login detection module — detect login walls, wait for manual login, handle CAPTCHA."""

import time


class LoginDetector:
    """Detect login walls and wait for manual user login."""

    def __init__(self, tab):
        self.tab = tab

    def is_login_required(self) -> bool:
        """Check if the page REDIRECTED to a login page (URL-level)."""
        url = self.tab.url.lower()
        return any(p in url for p in ("/login", "/signin", "/auth"))

    def wait_for_login(self, timeout: int = 300) -> bool:
        """Wait for the user to manually log in.

        Polls URL every second; returns True when login is detected,
        False on timeout.

        After login, handles verification popups and refreshes the page.
        """
        check_interval = 1.0
        elapsed = 0.0

        while elapsed < timeout:
            time.sleep(check_interval)
            elapsed += check_interval
            current_url = self.tab.url

            if "/login" not in current_url and "/signin" not in current_url:
                print(f"Login detected, current page: {current_url}")
                break

            if elapsed % 30 < check_interval:
                print(f"  Waiting for login... ({int(elapsed)}s)")

        else:
            return False

        self._handle_verify()

        time.sleep(3)

        self.tab.get(self.tab.url)

        return True

    def _page_text(self) -> str:
        """Get page body text for login keyword detection."""
        try:
            return self.tab.run_js("return document.body.innerText || '';") or ""
        except Exception:
            return ""

    def _handle_verify(self):
        """Wait for any verification popup to be manually resolved."""
        verify_selectors = [
            ".nc_wrapper",
            "text=安全验证",
            "text=请通过验证",
        ]

        while True:
            triggered = False
            for sel in verify_selectors:
                try:
                    el = self.tab.ele(sel, timeout=1)
                    if el:
                        triggered = True
                        break
                except Exception:
                    continue

            if not triggered:
                break
            print("Security verification detected, please complete in browser...")
            time.sleep(2)
