"""Browser module — Chromium lifecycle, tab management, text extraction.

Each tab is identified by a CDP targetId (full UUID).  Display uses the
first 8 chars as a short ID.  All tab lookups use prefix matching so
AI can pass the short ID and still locate the full tab.

Playwright async API: one persistent BrowserContext = one session,
its pages are the tabs.  All methods that touch Playwright are async.

浏览器怎么起（三种模式，按优先级）
----------------------------------
1. ``BROWSER_ADDRESS`` 有值 → ``connect_over_cdp``（接管已有浏览器，不动它）
2. 否则 → **我们自己 Popen 一个普通 Chrome**（``--remote-debugging-port`` +
   持久 profile），再 ``connect_over_cdp``。见 ``chromium.py`` 里关于指纹的解释：
   这条路上 ``navigator.webdriver=false``、没有 Playwright 的注入痕迹与启动开关。
3. 找不到 Chrome/Edge → 回退到 Playwright 启动（``launch_persistent_context``），
   功能一致但会带上自动化指纹，往 stderr 说明一次。

状态观测：页面自己跳转 / 标签页增删都会 ``observation.mark_dirty()`` ——
那是"工具之外发生的变化"，AI 必须重新建档才能继续操作。
"""

import asyncio
import os
import sys
import uuid

from playwright.async_api import BrowserContext, Page, Playwright

from veddata import chromium, observation, paths


class BrowserSession:
    """Manages a single Chromium instance with multiple tabs."""

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None   # persistent context
        self._pages: dict[str, Page] = {}             # tab_id (CDP targetId) → Page
        self._page_to_id: dict[int, str] = {}         # id(page) → tab_id
        self._urls: dict[int, str] = {}               # id(page) → last seen URL
        self._current_tab: str | None = None          # active tab_id
        self._auto_page_hook = False
        self._launcher: chromium.Launcher | None = None
        self._mode = ""                               # attach / own / fallback
        self._note = ""

    # ---- 启动 / 接管 ----

    async def _ensure_browser(self) -> BrowserContext:
        if self._context is not None:
            return self._context

        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()

        headless = os.environ.get("HEADLESS", "false") == "true"
        address = os.environ.get("BROWSER_ADDRESS", "").strip()

        if address:
            self._mode = "attach"
            self._note = f"attached to {address}"
        else:
            try:
                self._launcher = chromium.Launcher()
                address = self._launcher.ensure(paths.profile_dir(), headless)
                self._mode = "own"
                self._note = f"launched {Path_label(self._launcher.path)} on {address}"
            except chromium.ChromiumError as exc:
                # 没有可用的 Chrome/Edge → 回退到 Playwright（会带自动化指纹）
                print(f"[veddata] {exc}；回退到 Playwright 启动（该路径带自动化指纹，"
                      f"部分站点会拦截）", file=sys.stderr)
                self._mode = "fallback"
                self._note = "playwright launch (fallback)"
                self._context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(paths.profile_dir()),
                    headless=headless,
                )
                self._after_attach()
                return self._context

        # no_defaults=True：不要 Playwright 的默认覆盖（focus emulation、
        # colorScheme/reducedMotion/forcedColors/contrast 媒体模拟、acceptDownloads）。
        # DrissionPage 走的是裸 CDP，什么都不套 —— 我们对齐它，别给页面留下可观测的差异。
        browser = await self._playwright.chromium.connect_over_cdp(address, no_defaults=True)
        contexts = browser.contexts
        self._context = contexts[0] if contexts else await browser.new_context()
        self._after_attach()
        return self._context

    def _after_attach(self) -> None:
        if self._auto_page_hook or self._context is None:
            return
        self._auto_page_hook = True
        # 页面自己开的新标签页（target=_blank / window.open）→ 自动登记 + 状态置脏
        self._context.on("page", self._on_new_page)

    # ---- 自动注册（页面自身打开的新标签页） ----

    def _on_new_page(self, page: Page) -> None:
        """sync 回调：派发到事件循环执行异步注册，不抢占当前 tab。"""
        observation.mark_dirty("新标签页被打开（页面自己或用户）")
        asyncio.create_task(self._auto_register(page))

    async def _auto_register(self, page: Page) -> None:
        await self._register_tab(page, set_current=False)

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
        try:
            self._urls[id(page)] = page.url or ""
        except Exception:
            self._urls[id(page)] = ""

        # 页面关闭 → 账本失效
        page.on("close", lambda _p=page: self._on_page_closed(_p))
        # 主框架跳转 → 账本失效（工具自己发起的跳转会在工具返回时重新建档）
        page.on("framenavigated", lambda frame, _p=page: self._on_frame_navigated(_p, frame))

        if set_current:
            self._current_tab = tid
        # 事件监听统一挂接点（monitor / script registry / console）
        from veddata import state
        await state.attach_page(page)

    def _on_page_closed(self, page: Page) -> None:
        observation.mark_dirty("标签页被关闭（页面自己或用户）")
        self._unregister_tab(page)

    def _on_frame_navigated(self, page: Page, frame) -> None:
        """只看主框架：URL 真变了才置脏（hash 变化/iframe 不算）。"""
        try:
            if frame is not page.main_frame:
                return
            url = frame.url or ""
        except Exception:
            return
        previous = self._urls.get(id(page))
        if previous is None:
            self._urls[id(page)] = url
            return
        if url != previous and url not in ("about:blank", "") :
            self._urls[id(page)] = url
            observation.mark_dirty(f"页面跳转 → {url[:80]}")

    def _unregister_tab(self, page: Page) -> None:
        """页面关闭时清理其所有追踪状态。"""
        tid = self._page_to_id.pop(id(page), None)
        self._urls.pop(id(page), None)
        if tid is None:
            return
        self._pages.pop(tid, None)
        from veddata import state
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
        """标签页清单：短 ID + URL + 标题（AI 靠它知道"每个页都在哪"）。"""
        context = await self._ensure_browser()
        lines = [f"Open tabs ({len(self._pages)}):"]
        for tid, page in self._pages.items():
            try:
                title = (await page.title() or "")[:60]
            except Exception:
                title = ""
            try:
                url = (page.url or "")[:120]
            except Exception:
                url = ""
            mark = " ← current" if tid == self._current_tab else ""
            lines.append(f"  [{tid[:8]}] {url}{mark}")
            if title:
                lines.append(f"            {title}")
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

    def mode_note(self) -> str:
        """当前浏览器怎么来的（排查用，也进 ved_status）。"""
        return self._note or "(not started)"

    async def close(self) -> str:
        """关闭/断开浏览器并清空所有捕获数据。

        自己起的浏览器 → 关掉；接管来的（``BROWSER_ADDRESS``）→ 只断开，不动它。
        """
        if self._mode == "fallback" and self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        if self._launcher is not None:
            started = self._launcher.started
            self._launcher.stop(paths.profile_dir())
            note = "Browser closed." if started else "Detached (browser left running)."
            self._launcher = None
        else:
            note = "Browser closed."

        self._context = None
        self._pages.clear()
        self._page_to_id.clear()
        self._urls.clear()
        self._current_tab = None
        self._auto_page_hook = False
        self._mode = ""
        self._note = ""
        observation.reset()
        return note

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


def Path_label(path: str | None) -> str:                                           # noqa: N802
    """简短浏览器标识（日志/状态里用）。"""
    if not path:
        return "(unknown browser)"
    return os.path.basename(path)
