"""Browser module — Chromium lifecycle, page navigation, text extraction."""

import os
import re

from DrissionPage import Chromium, ChromiumOptions
from trafilatura import extract as trafilatura_extract


class BrowserSession:
    """Manages a Chromium browser session for page navigation and text extraction."""

    def __init__(self):
        self.port: int | None = None

        if os.environ.get("HEADLESS", "false") == "true":
            headless = True
        else:
            headless = False

        browser_path = os.environ.get("BROWSER_PATH", "")
        user_data = os.environ.get("USER_DATA_DIR", "")

        address = os.environ.get("BROWSER_ADDRESS", "")
        if address:
            co = ChromiumOptions().set_address(address)
            self._browser = Chromium(co)
            self.tab = self._browser.latest_tab
            return

        # 默认单端口模式; 设置 MULTI_BROWSER=true 使用 10 端口池
        use_multi = os.environ.get("MULTI_BROWSER", "false") == "true"
        port_range = range(9222, 9232) if use_multi else range(9222, 9223)

        for port in port_range:
            try:
                co = ChromiumOptions().set_local_port(port)
                if headless:
                    co.headless(True)
                if browser_path == "edge":
                    co.set_browser_path(edge=True)
                elif browser_path:
                    co.set_browser_path(browser_path)
                if user_data:
                    co.set_user_data_path(user_data)
                self._browser = Chromium(co)
                self.tab = self._browser.latest_tab
                self.port = port
                return
            except Exception:
                continue
        raise RuntimeError(
            "所有浏览器端口 (9222-9231) 均被占用。\n"
            "请调用 scout_list_browsers() 查看占用情况，"
            "然后使用 scout_close(port=N) 关闭空闲浏览器释放端口。"
        )

    def open(self, url: str) -> dict:
        """Open URL and return page info.

        Returns:
            dict with keys: title, text
        """
        self.tab.get(url)
        try:
            self.tab.wait.eles_loaded('a, button, input', timeout=5, any_one=True)
        except Exception:
            pass
        title = self.tab.title
        text = self.get_text()
        return {"title": title, "text": text}

    def get_text(self) -> str:
        """Extract page text as Markdown using trafilatura, fallback to regex."""
        html = self.tab.html
        max_len = int(os.environ.get("MAX_TEXT_LENGTH", "3000"))

        if os.environ.get("TEXT_EXTRACTOR", "") != "legacy":
            try:
                result = trafilatura_extract(
                    html,
                    output_format='markdown',
                    include_tables=True,
                    include_links=False,
                    include_images=False,
                    include_comments=False,
                    favor_precision=True,
                )
                if result and len(result.strip()) > 20:
                    return result[:max_len]
            except Exception:
                pass

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

        return text[:max_len]

    def close(self):
        """Close the browser."""
        try:
            self._browser.quit()
        except Exception:
            pass

    
