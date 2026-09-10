"""页面事实采集：只说"有什么"，不判定、不引导。

仓库既定原则：**工具输出只陈述事实，不含"下一步该做什么"**（见 084e8dd）。
所以这里不判"这是不是人机验证 / 要不要叫用户" —— 那是 AI 看事实自己决定的事。
我们只递材料：

- 最终 URL / 标题 / 正文字数 / 链接数
- 正文样本（前若干字**原文**）
- 命中关键词的**原文片段**（命中词 + 前后各 60 字，原样，不加工）
- 可见的表单与组件（选择器 + 尺寸）；隐藏的单独列出
- 正文规模相对"上次同一地址"的变化（只报数字）

没有任何 kind / confidence / 建议动作。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

_SNIPPET = 200
_CONTEXT = 60

# 只用来"找片段"，不用来判定性质
_WATCH_WORDS = [
    "验证", "安全验证", "人机", "滑块", "验证码", "登录", "请完成", "风控", "访问受限",
    "请求过于频繁", "captcha", "verify", "challenge", "checking your browser", "just a moment",
    "unusual traffic", "too many requests", "forbidden", "blocked",
]

# 常见的验证/登录组件选择器（同样只用来"列出事实"）
_WIDGET_LIST = [
    "#nc_1_wrapper", ".nc-container", ".geetest_panel", ".geetest_holder", ".geetest_box",
    ".cf-turnstile", "#challenge-form", ".g-recaptcha", ".h-captcha", "#captcha",
    ".verify-wrap", ".verify-box", "iframe[src*='recaptcha']", "iframe[src*='hcaptcha']",
    "iframe[src*='challenges.cloudflare.com']", "iframe[src*='captcha']",
    "input[type=password]", "input[name*='captcha' i]",
]

_baselines: dict[str, tuple[str, int]] = {}


@dataclass
class Facts:
    url: str = ""
    title: str = ""
    length: int = 0
    links: int = 0
    sample: str = ""
    hits: list[tuple[str, str]] = field(default_factory=list)     # (命中词, 原文片段)
    visible: list[tuple[str, str]] = field(default_factory=list)   # (选择器, 尺寸)
    hidden: list[str] = field(default_factory=list)
    size_change: str = ""


_DETECT_JS = """
() => {
  const body = document.body;
  const text = body ? (body.innerText || '') : '';
  const seen = (el) => {
    try {
      const rect = el.getBoundingClientRect();
      return (el.offsetWidth > 0 || el.offsetHeight > 0) && rect.width > 20 && rect.height > 20;
    } catch (e) { return false; }
  };
  const shown = [], hidden = [];
  for (const sel of %s) {
    const nodes = [...document.querySelectorAll(sel)];
    if (!nodes.length) continue;
    const hit = nodes.find(seen);
    if (hit) {
      const rect = hit.getBoundingClientRect();
      shown.push([sel, Math.round(rect.width) + 'x' + Math.round(rect.height)]);
    } else {
      hidden.push(sel);
    }
  }
  return {
    url: location.href,
    title: document.title || '',
    length: text.length,
    links: document.querySelectorAll('a[href]').length,
    sample: text.slice(0, %d),
    widgetsVisible: shown,
    widgetsHidden: hidden,
  };
}
""" % (json.dumps(_WIDGET_LIST), _SNIPPET)


def _facts(info: dict, tab_id: str) -> Facts:
    """把页面读数整理成事实（不判定）。"""
    url = str(info.get("url", ""))
    text = str(info.get("sample", ""))
    length = int(info.get("length", 0))
    facts = Facts(url=url, title=str(info.get("title", "")), length=length,
                  links=int(info.get("links", 0)), sample=text,
                  visible=[tuple(item) for item in (info.get("widgetsVisible") or [])],
                  hidden=list(info.get("widgetsHidden") or []))

    lowered = text.lower()
    for word in _WATCH_WORDS:
        position = lowered.find(word.lower())
        if position < 0:
            continue
        start = max(0, position - _CONTEXT)
        end = min(len(text), position + len(word) + _CONTEXT)
        facts.hits.append((word, text[start:end].replace("\n", " ")))
        if len(facts.hits) >= 6:
            break

    baseline = _baselines.get(tab_id)
    if baseline and baseline[0].split("?")[0] == url.split("?")[0] and baseline[1] != length:
        facts.size_change = f"{baseline[1]} → {length} chars (same address)"
    if length > 0:
        _baselines[tab_id] = (url, length)
    return facts


async def collect(page, tab_id: str = "") -> Facts | None:
    """读一次页面事实；页面不可用返回 None。"""
    try:
        info = await page.evaluate(_DETECT_JS)
    except Exception:                                                           # noqa: BLE001
        return None
    if not isinstance(info, dict):
        return None
    return _facts(info, tab_id)


def format_facts(facts: Facts) -> str:
    """把事实排成给 AI 看的一段（只有事实，没有建议）。"""
    lines = ["page facts",
             f"  url     : {facts.url[:160]}",
             f"  title   : {facts.title[:120]}",
             f"  body    : {facts.length} chars, {facts.links} links"]
    if facts.size_change:
        lines.append(f"  size    : {facts.size_change}")
    if facts.sample:
        lines.append(f"  sample  : {facts.sample[:200].replace(chr(10), ' ')}")
    if facts.hits:
        for word, context in facts.hits:
            lines.append(f"  hit     : {word} → \"{context}\"")
    else:
        lines.append("  hit     : (none)")
    if facts.visible:
        for selector, size in facts.visible[:5]:
            lines.append(f"  visible : {selector} {size}")
    else:
        lines.append("  visible : (none of the watched selectors)")
    if facts.hidden:
        lines.append(f"  hidden  : {', '.join(facts.hidden[:5])}")
    return "\n".join(lines)


def reset(tab_id: str = "") -> None:
    if tab_id:
        _baselines.pop(tab_id, None)
    else:
        _baselines.clear()


# ---- 调用方保持原调用形状（ved_goto / ved_act / ved_status / ved_chain），但语义已经是
# "只给事实"：hard 恒为 False —— 我们不再替 AI 判定"要不要停下来叫用户"。
Gate = Facts
detect_async = collect


def format_gate(facts: Facts, prefix: str = "") -> str:
    return format_facts(facts)


Facts.hard = property(lambda self: False)      # 永久 False：不判定
