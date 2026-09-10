"""人机门检测：登录页 / 验证码 / 风控页 —— 只发现、不处理。

我们不做对抗、不自动打码。发现之后由工具把话说明白：AI 转述给用户，
用户在**可见窗口**里处理（登录 / 过验证），处理完让 AI 继续 ——
全程不阻塞、不轮询、不挂起（对齐"等待交给人和 AI，工具只负责报告"）。

判据分两档（避免误伤）
----------------------
- **强信号**（单独命中即判定）：URL 落在验证/登录类路径；页面出现已知验证组件
  （极验 / 阿里滑块 / reCAPTCHA / hCaptcha / Cloudflare / 通用 captcha）；
  文案命中验证措辞；存在密码输入框（登录）
- **弱信号**（只提示，不硬停）：正文规模相对"上次看到的大小"塌缩
  —— 实测参照：zhipin 城市页 2917 字 → 验证页 101 字 → 被擦 0 字

对齐项目既有口径：结构化、可行动、带恢复动作（同 ``watch_policy.remediate``）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LOGIN = "login"
CAPTCHA = "captcha"
RISK_CONTROL = "risk_control"

_VERIFY_URL = re.compile(
    r"(verify|captcha|challenge|security[-_]?check|risk[-_]?control|/safe\b|robot|geetest|"
    r"verify\.html|人机|验证)",
    re.I,
)
_LOGIN_URL = re.compile(r"(/(login|signin|sign-in|logon|passport|auth)\b|login\.htm|signin\.htm)", re.I)

_WIDGETS = ",".join([
    "#nc_1_wrapper", ".nc-container", ".geetest_panel", ".geetest_holder", ".geetest_box",
    ".cf-turnstile", "#challenge-form", ".g-recaptcha", ".h-captcha",
    "iframe[src*='recaptcha']", "iframe[src*='hcaptcha']", "iframe[src*='challenges.cloudflare.com']",
    "iframe[src*='captcha']", "input[name*='captcha' i]", "#captcha", ".verify-wrap", ".verify-box",
])

_MARKERS = [
    ("captcha", ("请完成验证", "人机验证", "安全验证", "滑块验证", "拖动滑块", "验证码", "图形验证",
                 "滑动验证", "点击验证", "安全检测", "访问验证", "verify you are human",
                 "complete the captcha", "prove you are human")),
    ("risk_control", ("checking your browser", "just a moment", "unusual traffic",
                      "enable javascript and cookies", "ddos protection", "too many requests",
                      "请求过于频繁", "访问受限", "拒绝访问", "系统检测到")),
    ("login", ("请登录", "登录后", "sign in to continue", "log in to continue", "please log in")),
]

_SNIPPET = 600
_baselines: dict[str, tuple[str, int]] = {}


@dataclass
class Gate:
    """一次人机门判定结果。"""

    kind: str
    confidence: str                      # high / medium / low
    url: str = ""
    title: str = ""
    evidence: list[str] = field(default_factory=list)

    @property
    def hard(self) -> bool:
        """是否硬停（中/高置信才打断用户）。"""
        return self.confidence in ("high", "medium")


_DETECT_JS = """
() => {
  const body = document.body;
  const text = body ? (body.innerText || '') : '';
  return {
    url: location.href,
    title: document.title || '',
    text: text.slice(0, %d),
    len: text.length,
    password: !!document.querySelector('input[type=password]'),
    widgets: document.querySelectorAll(%r).length,
  };
}
""" % (_SNIPPET, _WIDGETS)


def _judge(info: dict, tab_id: str) -> Gate | None:
    url = str(info.get("url", ""))
    title = str(info.get("title", ""))
    text = str(info.get("text", ""))
    length = int(info.get("len", 0))
    lowered = text.lower()

    if url and _VERIFY_URL.search(url):
        return Gate(RISK_CONTROL, "high", url, title, [f"URL 命中验证类路径：{url[:120]}"])
    if info.get("widgets"):
        return Gate(CAPTCHA, "high", url, title, [f"页面里有 {info['widgets']} 个已知验证组件"])
    for kind, markers in _MARKERS:
        for marker in markers:
            if marker.lower() in lowered:
                return Gate(kind, "high", url, title, [f"页面文案命中：{marker}"])
    if url and _LOGIN_URL.search(url):
        return Gate(LOGIN, "medium", url, title, [f"URL 命中登录类路径：{url[:120]}"])
    if info.get("password"):
        return Gate(LOGIN, "medium", url, title, ["页面里有密码输入框"])

    baseline = _baselines.get(tab_id)
    if baseline and baseline[0].split("?")[0] == url.split("?")[0] and length < 200 and baseline[1] >= 800:
        return Gate(RISK_CONTROL, "low", url, title,
                    [f"正文从 {baseline[1]} 字缩到 {length} 字（同一地址）"])

    if length > 0:
        _baselines[tab_id] = (url, length)          # 正常页面才更新基线
    return None


def remember(tab_id: str, url: str, length: int) -> None:
    """外部记录一次"正常页面"基线（工具读页面时调）。"""
    if length > 0:
        _baselines[tab_id] = (url, length)


def reset(tab_id: str = "") -> None:
    """清基线（关浏览器/关标签页时调）。"""
    if tab_id:
        _baselines.pop(tab_id, None)
    else:
        _baselines.clear()


def format_gate(gate: Gate, prefix: str = "") -> str:
    """把判定结果写成**给 AI 直接转述**的话：要用户做什么、做完怎么办。"""
    if gate.kind == LOGIN:
        headline = "需要人工：登录"
        todo = "请用户在浏览器窗口里登录（profile 是持久的，登录态会保留，之后不用重登）"
    elif gate.kind == CAPTCHA:
        headline = "需要人工：人机验证"
        todo = "请用户在浏览器窗口里完成验证（滑块/点选/图形验证码）"
    else:
        headline = "需要人工：安全验证（风控）"
        todo = "请用户在浏览器窗口里完成验证；这类页面通常带 callbackUrl，过完会自动跳回原页"

    lines = [f"{prefix}" if prefix else "", f"⚠️ {headline}"]
    if gate.evidence:
        lines.append("证据：" + "；".join(gate.evidence))
    if gate.title:
        lines.append(f"当前页面：{gate.title}")
    lines.append(f"做什么：{todo}")
    lines.append("完成后：**不要重新导航**（会再次触发风控）—— 先调 ved_status() 确认状态，"
                 "再从当前页继续（ved_apis / ved_dom_tree / ved_act…）")
    lines.append("数据层不受影响：已捕获的 API 仍可用 ved_apis / ved_inspect 查看。")
    if not gate.hard:
        lines.insert(1, "（低置信提示：可能只是页面变空，建议先跟用户确认一下）")
    return "\n".join(line for line in lines if line != "")


async def detect_async(page, tab_id: str = "") -> Gate | None:
    """异步版（工具里用这个）。"""
    try:
        info = await page.evaluate(_DETECT_JS)
    except Exception:                                                           # noqa: BLE001
        return None
    if not isinstance(info, dict):
        return None
    return _judge(info, tab_id)
