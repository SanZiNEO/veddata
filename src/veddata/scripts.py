"""Script registry — collect and search loaded JS sources.

Sources come from CDP Debugger.scriptParsed events (attached before
navigation) plus a lazy seed scan of <script[src]> and performance
resource entries.  Source text is fetched via Debugger.getScriptSource
or, as fallback, page.request.get(url).
"""

import re

from veddata import limits


class ScriptRegistry:
    def __init__(self, page, cdp=None):
        self._page = page
        self._cdp = cdp
        self._scripts: dict[str, dict] = {}    # url → {script_id, length, start_line}
        self._sources: dict[str, str] = {}     # url → text（缓存）
        self._seeded = False
        self._attached = False
        self._enabled = False

    async def attach(self, cdp) -> None:
        """只挂事件监听，**不开 Debugger**。

        默认不开调试器：DrissionPage / 裸 CDP 客户端都是"用到才 enable"，
        Playwright 自己也不开。我们以前在每个页面上都 `Debugger.enable` ——
        等于主动告诉页面"有调试器连着"，站点自检就能看见。
        真正需要脚本清单/源码时再调 :meth:`enable`（Chrome 会把已加载脚本重新
        scriptParsed 一遍，所以迟开不会漏）。
        """
        if self._attached:
            return
        self._attached = True
        self._cdp = cdp

        def on_script_parsed(params):
            url = params.get("url", "")
            if not url:
                return
            self._scripts.setdefault(url, {
                "script_id": params.get("scriptId", ""),
                "length": params.get("length", 0),
                "start_line": params.get("startLine", 0),
            })

        cdp.on("Debugger.scriptParsed", on_script_parsed)

    async def enable(self) -> None:
        """按需开 Debugger（幂等）。开了之后 Chrome 会重发已加载脚本的 scriptParsed。"""
        if self._enabled or not self._cdp:
            return
        self._enabled = True
        try:
            await self._cdp.send("Debugger.enable")
        except Exception:
            self._enabled = False

    async def seed(self) -> None:
        """补齐 attach 之前已加载的脚本 URL（无 script_id，走网络获取）。"""
        if self._seeded:
            return
        self._seeded = True
        try:
            urls = await self._page.evaluate("""
            () => {
              const s = new Set();
              for (const el of document.querySelectorAll('script[src]')) s.add(el.src);
              for (const e of performance.getEntriesByType('resource')) {
                if (e.initiatorType === 'script') s.add(e.name);
              }
              return Array.from(s);
            }
            """)
        except Exception:
            return
        for url in urls or []:
            self._scripts.setdefault(url, {
                "script_id": "",
                "length": 0,
                "start_line": 0,
            })

    async def get_source(self, url: str) -> str | None:
        """返回脚本源码（缓存）。CDP 拿不到时用 page.request 下载。

        第一次真要读脚本时才开 Debugger（见 :meth:`enable`）—— 平时不挂着调试器，
        和 DrissionPage / 裸 CDP 客户端"用到才 enable"一致。
        """
        await self.enable()
        if url in self._sources:
            return self._sources[url]
        info = self._scripts.get(url)
        if info and info.get("script_id") and self._cdp:
            try:
                result = await self._cdp.send("Debugger.getScriptSource", {"scriptId": info["script_id"]})
                source = result.get("scriptSource", "")
                if source:
                    self._cache(url, source)
                    return source
            except Exception:
                pass
        try:
            resp = await self._page.request.get(url)
            if resp.ok:
                source = await resp.text()
                self._cache(url, source)
                return source
        except Exception:
            pass
        return None

    def _cache(self, url: str, source: str) -> None:
        if len(source) > 2 * 1024 * 1024:
            return
        self._sources[url] = source
        total = sum(len(s) for s in self._sources.values())
        while total > 20 * 1024 * 1024 and len(self._sources) > 1:
            oldest = next(iter(self._sources))
            total -= len(self._sources.pop(oldest))

    def search(self, query: str, regex: bool = False) -> list[dict]:
        """按文件分组搜索：返回 [{url, matches: [{line, text}]}]，单文件上限 200 条。"""
        if regex:
            try:
                pat = re.compile(query)
            except re.error:
                pat = re.compile(re.escape(query))
        else:
            pat = re.compile(re.escape(query))
        results = []
        for url, source in self._sources.items():
            matches = []
            for i, line in enumerate(source.splitlines(), start=1):
                if pat.search(line):
                    matches.append({"line": i, "text": line.strip()[:200]})
                    if len(matches) >= 200:
                        break
            if matches:
                results.append({"url": url, "matches": matches})
        return results

    def list_scripts(self) -> str:
        lines = []
        for url, info in self._scripts.items():
            source = self._sources.get(url)
            size = len(source) if source is not None else info.get("length", 0)
            line_count = source.count("\n") + 1 if source is not None else 0
            label = limits.describe_inline(url)   # data: URI 只给摘要，绝不吐内容
            if label != url:
                # 内联脚本：只给摘要，不再重复后面的字节/行数（两者口径不同，容易误导）
                lines.append(label)
            else:
                lines.append(f"{label} ({size} bytes, {line_count} lines)")
        if not lines:
            return "(no scripts)"
        return "\n".join(sorted(lines))
