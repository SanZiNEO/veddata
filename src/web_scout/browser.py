"""Browser module — Chromium lifecycle, tab management, text extraction.

Each tab is identified by a CDP targetId (full UUID).  Display uses the
first 8 chars as a short ID.  All tab lookups use prefix matching so
AI can pass the short ID and still locate the full tab.

Playwright async API: one persistent BrowserContext = one session,
its pages are the tabs.  All methods that touch Playwright are async.

Auto-registration: pages opened by the page itself (target="_blank",
window.open) are registered automatically via context.on("page") so
their network traffic joins the shared capture pool, tagged by tab_id.
"""

import asyncio
import os
import uuid

from playwright.async_api import BrowserContext, Page, Playwright


class BrowserSession:
    """Manages a single Chromium instance with multiple tabs.

    Launch modes:
      - BROWSER_ADDRESS env set  → connect_over_cdp(existing browser)
      - otherwise                → launch_persistent_context(user_data_dir)
    """

    def __init__(self):
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None   # persistent context
        self._pages: dict[str, Page] = {}             # tab_id (CDP targetId) → Page
        self._page_to_id: dict[int, str] = {}         # id(page) → tab_id
        self._current_tab: str | None = None          # active tab_id
        self._auto_page_hook = False

    async def _ensure_browser(self) -> BrowserContext:
        if self._context is not None:
            return self._context

        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()

        headless = os.environ.get("HEADLESS", "false") == "true"
        browser_path = os.environ.get("BROWSER_PATH", "")
        user_data = os.environ.get("USER_DATA_DIR", "")
        address = os.environ.get("BROWSER_ADDRESS", "")

        if address:
            browser = await self._playwright.chromium.connect_over_cdp(address)
            contexts = browser.contexts
            self._context = contexts[0] if contexts else await browser.new_context()
        else:
            channel = "msedge" if browser_path == "edge" else (browser_path or None)
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=user_data or ".web-scout-data",
                headless=headless,
                channel=channel,
            )

        # 自动注册页面自身打开的新 tab（弹窗 / target=_blank）
        if not self._auto_page_hook:
            self._auto_page_hook = True
            self._context.on("page", self._on_new_page)

        return self._context

    # ---- 自动注册（页面自身打开的新标签页） ----

    def _on_new_page(self, page: Page) -> None:
        """sync 回调：派发到事件循环执行异步注册，不抢占当前 tab。"""
        asyncio.create_task(self._auto_register(page))

    async def _auto_register(self, page: Page) -> None:
        await self._register_tab(page, set_current=False)
        page.on("close", lambda _p=page: self._unregister_tab(_p))

    async def _register_tab(self, page: Page, set_current: bool = True) -> None:
        """Register a page as a tab, keyed by CDP targetId (fallback uuid4)."""
        tid = ""
        try:
            session = await page.context.new_cdp_session(page)
            info = await session.send("Target.getTargetInfo")
            tid = info.get("targetInfo", {}).get("targetId", "")
        except Exception:
            tid = ""
        if not tid:
            tid = uuid.uuid4().hex
        self._pages[tid] = page
        self._page_to_id[id(page)] = tid
        if set_current:
            self._current_tab = tid
        # 事件监听统一挂接点（monitor / script registry / console）
        from web_scout import state
        await state.attach_page(page)

    def _unregister_tab(self, page: Page) -> None:
        """页面关闭时清理其所有追踪状态。"""
        tid = self._page_to_id.pop(id(page), None)
        if tid is None:
            return
        self._pages.pop(tid, None)
        from web_scout import state
        state._dom_trees.pop(tid, None)
        state._script_registries.pop(tid, None)
        state._watches.pop(tid, None)
        pool = state.get_pool()
        if pool:
            pool.prune(tid)
        if self._current_tab == tid:
            remaining = list(self._pages)
            self._current_tab = remaining[0] if remaining else None

    async def open(self, url: str) -> dict:
        """Open a URL in a tab. Reuses blank tab or creates new one."""
        context = await self._ensure_browser()
        page = None
        for p in context.pages:
            if p.url in ("about:blank", "", "chrome://newtab/"):
                page = p
                break
        if page is None:
            page = await context.new_page()
        await self._register_tab(page)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            return {"tab_id": self.current_tab_id(), "title": "", "text": f"Failed to navigate: {e}"}
        return await self._extract_page_info(page)

    def current_tab_id(self) -> str:
        return self._current_tab or ""

    def get_tab_url(self, tab_id_str: str) -> str:
        tid = self.resolve_tab_id(tab_id_str)
        page = self._pages.get(tid) if tid else None
        if page is None:
            return ""
        return (page.url or "")[:60]

    def resolve_tab_id(self, short_id: str) -> str | None:
        """Prefix-match a short ID to a full tab_id."""
        if not short_id:
            return None
        for tid in self._pages:
            if tid.startswith(short_id):
                return tid
        return None

    async def get_current_page(self) -> Page | None:
        context = await self._ensure_browser()
        if self._current_tab and self._current_tab in self._pages:
            return self._pages[self._current_tab]
        pages = context.pages
        if pages:
            self._current_tab = self._page_to_id.get(id(pages[-1]))
            return pages[-1]
        return None

    async def get_page_by_id(self, tab_id_str: str) -> Page | None:
        """Get a Page by CDP ID or short ID (prefix matched)."""
        context = await self._ensure_browser()
        tid = self.resolve_tab_id(tab_id_str)
        if tid and tid in self._pages:
            self._current_tab = tid
            return self._pages[tid]
        return None

    async def switch_tab(self, tab_id_str: str) -> str:
        page = await self.get_page_by_id(tab_id_str)
        if page:
            short = tab_id_str[:8] if len(tab_id_str) >= 8 else tab_id_str
            return f"Switched to tab {short}"
        short = tab_id_str[:8] if len(tab_id_str) >= 8 else tab_id_str
        return f"Tab {short} not found"

    async def list_tabs(self) -> str:
        context = await self._ensure_browser()
        lines = [f"Open tabs ({len(self._pages)}):"]
        for tid, page in self._pages.items():
            try:
                title = (await page.title() or "")[:60]
            except Exception:
                title = ""
            mark = " ← current" if tid == self._current_tab else ""
            lines.append(f"  [{tid[:8]}] {title}{mark}")
        return "\n".join(lines)

    async def close_tab(self, tab_id_str: str | None = None) -> str:
        await self._ensure_browser()
        tid = self.resolve_tab_id(tab_id_str) if tab_id_str else self._current_tab
        if not tid:
            return "No tab to close."
        page = self._pages.get(tid)
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass
        self._unregister_tab(page)
        short = tid[:8]
        return f"Tab {short} closed."

    async def close(self) -> str:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        self._pages.clear()
        self._page_to_id.clear()
        self._current_tab = None
        return "Browser closed."

    async def _extract_page_info(self, page: Page) -> dict:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        try:
            title = await page.title() or ""
        except Exception:
            title = ""
        text = await self._get_text(page)
        return {"tab_id": self.current_tab_id(), "title": title, "text": text}

    async def get_text(self) -> str:
        page = await self.get_current_page()
        if page is None:
            return ""
        return await self._get_text(page)

    @staticmethod
    async def _get_text(page: Page) -> str:
        max_len = int(os.environ.get("MAX_TEXT_LENGTH", "3000"))
        try:
            text = await page.evaluate("document.body.innerText || ''")
            if text:
                return text[:max_len]
        except Exception:
            pass
        return ""
