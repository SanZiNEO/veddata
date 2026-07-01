"""Browser module — Chromium lifecycle, tab management, text extraction."""

import os

from DrissionPage import Chromium, ChromiumOptions


class BrowserSession:
    """Manages a single Chromium instance with multiple tabs.

    Each tab gets a sequential number (1, 2, 3...) for AI-friendly reference.
    """

    def __init__(self):
        self._browser: Chromium | None = None
        self._tabs: dict[str, dict] = {}       # tab_id → {num, url, title}
        self._current_tab: str | None = None    # active tab_id
        self._next_tab_num: int = 1

    def _ensure_browser(self) -> Chromium:
        if self._browser and self._browser.states.is_alive:
            return self._browser

        if os.environ.get("HEADLESS", "false") == "true":
            headless = True
        else:
            headless = False

        browser_path = os.environ.get("BROWSER_PATH", "")
        user_data = os.environ.get("USER_DATA_DIR", "")
        address = os.environ.get("BROWSER_ADDRESS", "")

        if address:
            co = ChromiumOptions().set_address(address)
        else:
            use_multi = os.environ.get("MULTI_BROWSER", "false") == "true"
            port = 9222
            for p in (range(9222, 9232) if use_multi else range(9222, 9223)):
                try:
                    co = ChromiumOptions().set_local_port(p)
                    break
                except Exception:
                    port = p
                    continue
            if headless:
                co.headless(True)
            if browser_path == "edge":
                co.set_browser_path(edge=True)
            elif browser_path:
                co.set_browser_path(browser_path)
            if user_data:
                co.set_user_data_path(user_data)

        self._browser = Chromium(co)
        return self._browser

    def open(self, url: str) -> dict:
        """Open a URL in a tab. Reuses blank tab or creates new one.

        Returns:
            dict with keys: tab_num, title, text
        """
        browser = self._ensure_browser()

        # Try to reuse a blank tab
        for tid in browser.tab_ids:
            try:
                tab = browser.get_tab(tid)
                tab_url = str(tab.url or "")
                if tab_url in ("about:blank", "", "chrome://newtab/"):
                    tab.get(url)
                    self._register_tab(tab)
                    return self._extract_page_info(tab)
            except Exception:
                continue

        # Create new tab
        tab = browser.new_tab(url)
        self._register_tab(tab)
        return self._extract_page_info(tab)

    def _register_tab(self, tab) -> None:
        tid = tab.tab_id
        if tid not in self._tabs:
            self._tabs[tid] = {
                "num": self._next_tab_num,
                "url": str(tab.url or ""),
                "title": str(tab.title or ""),
            }
            self._next_tab_num += 1
        else:
            self._tabs[tid]["url"] = str(tab.url or "")
            self._tabs[tid]["title"] = str(tab.title or "")
        self._current_tab = tid

    def get_current_tab(self):
        """Get the currently active ChromiumTab."""
        browser = self._ensure_browser()
        if self._current_tab and self._current_tab in browser.tab_ids:
            return browser.get_tab(self._current_tab)
        return browser.latest_tab

    def get_tab_by_num(self, num: int):
        """Get a ChromiumTab by its display number (1, 2, 3...)."""
        browser = self._ensure_browser()
        for tid, info in self._tabs.items():
            if info["num"] == num and tid in browser.tab_ids:
                self._current_tab = tid
                return browser.get_tab(tid)
        return None

    def switch_tab(self, num: int) -> str:
        """Switch current tab by number. Returns status string."""
        tab = self.get_tab_by_num(num)
        if tab:
            return f"Switched to Tab #{num}"
        return f"Tab #{num} not found"

    def tab_num(self) -> int:
        return self._tabs.get(self._current_tab, {}).get("num", 0)

    def tab_label(self) -> str:
        """Return `[Tab #N]` label for the current tab."""
        num = self.tab_num()
        info = self._tabs.get(self._current_tab, {})
        url = (info.get("url") or "")[:60]
        return f"[Tab #{num}] {url}"

    def list_tabs(self) -> str:
        """Return a formatted list of all open tabs."""
        browser = self._ensure_browser()
        lines = [f"Open tabs ({len(browser.tab_ids)}):"]
        for tid in browser.tab_ids:
            info = self._tabs.get(tid, {})
            num = info.get("num", "?")
            title = (info.get("title") or str(browser.get_tab(tid).title or ""))[:60]
            mark = " ← current" if tid == self._current_tab else ""
            lines.append(f"  [Tab #{num}] {title}{mark}")
        return "\n".join(lines)

    def close_tab(self, num: int | None = None) -> str:
        """Close tab by number, or current tab if no number given."""
        browser = self._ensure_browser()
        if num is not None:
            tab = self.get_tab_by_num(num)
        else:
            tab = self.get_current_tab()
        if not tab:
            return "No tab to close."
        tid = tab.tab_id
        tab.close()
        self._tabs.pop(tid, None)
        if tid == self._current_tab:
            remaining = browser.tab_ids
            self._current_tab = remaining[0] if remaining else None
        return f"Tab #{num or self.tab_num()} closed."

    def close(self) -> str:
        """Close the entire browser."""
        if self._browser:
            self._browser.quit()
            self._browser = None
            self._tabs.clear()
            self._current_tab = None
        return "Browser closed."

    def _extract_page_info(self, tab) -> dict:
        """Extract title and text from a tab."""
        try:
            tab.wait.eles_loaded('a, button, input', timeout=5, any_one=True)
        except Exception:
            pass
        title = tab.title or ""
        text = self._get_text(tab)
        return {"tab_num": self.tab_num(), "title": title, "text": text}

    def get_text(self) -> str:
        return self._get_text(self.get_current_tab())

    @staticmethod
    def _get_text(tab) -> str:
        max_len = int(os.environ.get("MAX_TEXT_LENGTH", "3000"))
        try:
            text = tab.run_js("return document.body.innerText || ''")
            if text:
                return text[:max_len]
        except Exception:
            pass
        return ""
