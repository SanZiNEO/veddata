"""Browser module — Chromium lifecycle, page navigation, text extraction."""

import os
import re

from DrissionPage import Chromium, ChromiumOptions


class BrowserSession:
    """Manages a Chromium browser session for page navigation and text extraction."""

    def __init__(self):
        co = ChromiumOptions()

        address = os.environ.get("BROWSER_ADDRESS", "")
        if address:
            co.set_address(address)
        else:
            co.auto_port(True)

        if os.environ.get("HEADLESS", "false") == "true":
            co.headless(True)

        browser_path = os.environ.get("BROWSER_PATH", "")
        if browser_path == "edge":
            co.set_browser_path(edge=True)
        elif browser_path:
            co.set_browser_path(browser_path)

        user_data = os.environ.get("USER_DATA_DIR", "")
        if user_data:
            co.set_user_data_path(user_data)

        self._browser = Chromium(co)
        self.tab = self._browser.latest_tab

    def open(self, url: str) -> dict:
        """Open URL and return page info.

        Returns:
            dict with keys: title, text, api_count, is_login_required
        """
        self.tab.get(url)
        title = self.tab.title
        text = self.get_text()
        is_login = self._detect_login(text)
        return {
            "title": title,
            "text": text,
            "api_count": self._estimate_api_count(),
            "is_login_required": is_login,
        }

    def get_text(self) -> str:
        """Extract page text as Markdown, stripped of chrome elements."""
        html = self.tab.html

        html = re.sub(
            r'<script[^>]*>.*?</script>',
            "",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        html = re.sub(
            r'<style[^>]*>.*?</style>',
            "",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        html = re.sub(
            r'<nav[^>]*>.*?</nav>',
            "",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        html = re.sub(
            r'<header[^>]*>.*?</header>',
            "",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        html = re.sub(
            r'<footer[^>]*>.*?</footer>',
            "",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        html = re.sub(
            r'<noscript[^>]*>.*?</noscript>',
            "",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        html = re.sub(
            r'<svg[^>]*>.*?</svg>',
            "",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )

        text = re.sub(r'<[^>]+>', " ", html)
        text = re.sub(r'\n\s*\n', "\n", text)
        text = re.sub(r' {2,}', " ", text)
        text = text.strip()

        lines = text.split("\n")
        deduped = []
        prev = ""
        for line in lines:
            stripped = line.strip()
            if stripped and stripped == prev:
                continue
            deduped.append(line)
            prev = stripped
        text = "\n".join(deduped)

        max_len = int(os.environ.get("MAX_TEXT_LENGTH", "3000"))
        return text[:max_len]

    def close(self):
        """Close the browser."""
        try:
            self._browser.quit()
        except Exception:
            pass

    def _detect_login(self, text: str) -> bool:
        """Detect if the current page requires login by checking URL and text."""
        url = self.tab.url.lower()
        if any(p in url for p in ("/login", "/signin", "/auth")):
            return True

        text_lower = text.lower()
        if text_lower.count("请登录") >= 2:
            return True
        if "立即登录" in text_lower:
            return True
        if "扫码登录" in text_lower:
            return True
        return False

    @staticmethod
    def _estimate_api_count() -> int:
        """Placeholder: real API count comes from NetworkMonitor."""
        return 0
