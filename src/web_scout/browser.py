"""Browser module — Chromium lifecycle, tab management, text extraction.

Each tab is identified by its CDP tab_id (full UUID).  Display uses the
first 8 chars as a short ID.  All tab lookups use prefix matching so
AI can pass the short ID and still locate the full tab.
"""

import os

from DrissionPage import Chromium, ChromiumOptions


class BrowserSession:
    """Manages a single Chromium instance with multiple tabs.

    Keyed by CDP tab_id (full UUID, 36 chars).  Display uses first 8.
    """

    def __init__(self):
        self._browser: Chromium | None = None
        self._tabs: dict[str, dict] = {}       # tab_id → {url, title}
        self._current_tab: str | None = None    # active tab_id

    def _ensure_browser(self) -> Chromium:
        if self._browser and self._browser.states.is_alive:
            return self._browser

        headless = os.environ.get("HEADLESS", "false") == "true"
        browser_path = os.environ.get("BROWSER_PATH", "")
        user_data = os.environ.get("USER_DATA_DIR", "")
        address = os.environ.get("BROWSER_ADDRESS", "")

        if address:
            co = ChromiumOptions().set_address(address)
        else:
            use_multi = os.environ.get("MULTI_BROWSER", "false") == "true"
            for p in (range(9222, 9232) if use_multi else range(9222, 9223)):
                try:
                    co = ChromiumOptions().set_local_port(p)
                    break
                except Exception:
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
            dict with keys: tab_id, title, text
        """
        browser = self._ensure_browser()

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

        tab = browser.new_tab(url)
        self._register_tab(tab)
        return self._extract_page_info(tab)

    def _register_tab(self, tab) -> None:
        tid = tab.tab_id
        self._tabs[tid] = {
            "url": str(tab.url or ""),
            "title": str(tab.title or ""),
        }
        self._current_tab = tid

    def current_tab_id(self) -> str:
        return self._current_tab or ""

    def get_tab_url(self, tab_id_str: str) -> str:
        tid = self.resolve_tab_id(tab_id_str)
        if not tid:
            return ""
        info = self._tabs.get(tid, {})
        return (info.get("url") or "")[:60]

    def resolve_tab_id(self, short_id: str) -> str | None:
        """Prefix-match a short ID to a full CDP tab_id.

        Empty string defaults to current tab.
        """
        if not short_id:
            return self._current_tab
        if not self._browser:
            return None
        for tid in self._browser.tab_ids:
            if tid.startswith(short_id):
                return tid
        return None

    def get_current_tab(self):
        browser = self._ensure_browser()
        if self._current_tab and self._current_tab in browser.tab_ids:
            return browser.get_tab(self._current_tab)
        return browser.latest_tab

    def get_tab_by_id(self, tab_id_str: str):
        """Get a ChromiumTab by CDP ID or short ID (prefix matched)."""
        browser = self._ensure_browser()
        tid = self.resolve_tab_id(tab_id_str)
        if tid and tid in browser.tab_ids:
            self._current_tab = tid
            return browser.get_tab(tid)
        return None

    def switch_tab(self, tab_id_str: str) -> str:
        tab = self.get_tab_by_id(tab_id_str)
        if tab:
            short = tab_id_str[:8] if len(tab_id_str) >= 8 else tab_id_str
            return f"Switched to tab {short}"
        short = tab_id_str[:8] if len(tab_id_str) >= 8 else tab_id_str
        return f"Tab {short} not found"

    def list_tabs(self) -> str:
        browser = self._ensure_browser()
        lines = [f"Open tabs ({len(browser.tab_ids)}):"]
        for tid in browser.tab_ids:
            try:
                tab = browser.get_tab(tid)
                title = (tab.title or "")[:60]
            except Exception:
                title = ""
            mark = " ← current" if tid == self._current_tab else ""
            lines.append(f"  [{tid[:8]}] {title}{mark}")
        return "\n".join(lines)

    def close_tab(self, tab_id_str: str | None = None) -> str:
        browser = self._ensure_browser()
        tid = self.resolve_tab_id(tab_id_str) if tab_id_str else self._current_tab
        if not tid:
            return "No tab to close."
        try:
            tab = browser.get_tab(tid)
            tab.close()
        except Exception:
            pass
        self._tabs.pop(tid, None)
        if tid == self._current_tab:
            remaining = [t for t in browser.tab_ids if t != tid]
            self._current_tab = remaining[0] if remaining else None
        short = tid[:8]
        return f"Tab {short} closed."

    def close(self) -> str:
        if self._browser:
            try:
                self._browser.quit(timeout=3, force=True)
            except Exception:
                pass
            self._browser = None
            self._tabs.clear()
            self._current_tab = None
        # 确保 9222 上的进程被清理
        import subprocess
        try:
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.split("\n"):
                if ":9222" in line and "LISTENING" in line:
                    parts = line.strip().split()
                    if parts:
                        pid = parts[-1]
                        subprocess.run(["taskkill", "/f", "/pid", pid],
                                       capture_output=True, timeout=5)
                        break
        except Exception:
            pass
        return "Browser closed."

    def _extract_page_info(self, tab) -> dict:
        try:
            tab.wait.eles_loaded('a, button, input', timeout=5, any_one=True)
        except Exception:
            pass
        title = tab.title or ""
        text = self._get_text(tab)
        return {"tab_id": self.current_tab_id(), "title": title, "text": text}

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
