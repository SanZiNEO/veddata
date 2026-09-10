"""输出文件命名 —— 站点名 + 时间戳。

文件名形如 ``example_api-users_20260910-183045.json``：
- **站点名**：从 URL 解析，``www.example.com`` → ``example``，
  ``api.example.co.uk`` → ``example``。只做简单后缀定位，不求完备。
- **接口名**：URL 路径最后一段（清理后截断 32 字符）。
- **时间戳**：本地时间 ``YYYYMMDD-HHMMSS``，文件名安全且可排序。

同一个 URL 在同一秒被导出两次时才可能重名，那时追加 ``-2``、``-3``。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

# 常见的二级公共后缀（简单列举，够用即可；不在此列按单级后缀处理）
_TWO_LEVEL_SUFFIXES = frozenset({
    "com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "ac.cn",
    "com.hk", "com.tw", "com.mo", "com.au", "com.br", "com.sg", "com.my",
    "co.uk", "co.jp", "co.kr", "co.in", "co.nz",
})

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize(text: str) -> str:
    """把任意文本压成文件名安全的形式（小写、非法字符转 ``-``）。"""
    return _UNSAFE.sub("-", text).strip("-._").lower()


def _host(url: str) -> str:
    """取 host（容忍缺 scheme 的写法），拿不到返回空串。"""
    raw = url.strip()
    if not raw:
        return ""
    if "//" not in raw:
        raw = "//" + raw
    try:
        return (urlsplit(raw).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def site_name(url: str) -> str:
    """从 URL 提取站点名：``www.example.com`` → ``example``。

    规则（简单定位）：去掉前导 ``www.``，去掉公共后缀，取剩下最后一段。
    所以 ``api.example.com``、``cdn.example.com`` 都归到 ``example``。
    IP 直连按原样保留（``127.0.0.1``）；非 ASCII 前缀会被丢弃。
    """
    host = _host(url)
    if not host:
        return "unknown"
    if host.replace(".", "").isdigit():          # IPv4 直连
        return _sanitize(host) or "unknown"

    labels = host.split(".")
    if labels and labels[0] == "www":
        labels = labels[1:]
    if len(labels) > 1:
        if ".".join(labels[-2:]) in _TWO_LEVEL_SUFFIXES:
            labels = labels[:-2]
        else:
            labels = labels[:-1]

    return _sanitize(labels[-1]) if labels else "unknown"


def endpoint_name(url: str, fallback: str = "response") -> str:
    """URL 路径最后一段作为接口名，例：``/api/v2/users`` → ``users``。"""
    raw = url.strip()
    if "//" not in raw:
        raw = "//" + raw
    try:
        path = urlsplit(raw).path
    except ValueError:
        path = ""
    segments = [s for s in path.rstrip("/").split("/") if s]
    name = _sanitize(segments[-1]) if segments else fallback
    return (name or fallback)[:32]


def stamp(now: datetime | None = None) -> str:
    """本地时间戳，文件名安全可排序：``YYYYMMDD-HHMMSS``。"""
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def unique_path(directory: str | Path, stem: str, suffix: str) -> Path:
    """``<directory>/<stem><suffix>``；已存在则依次尝试 ``-2``、``-3``…"""
    directory = Path(directory)
    candidate = directory / f"{stem}{suffix}"
    counter = 1
    while candidate.exists():
        counter += 1
        candidate = directory / f"{stem}-{counter}{suffix}"
    return candidate


def export_stem(url: str) -> str:
    """导出的文件主干：``<站点名>_<接口名>_<时间戳>``。"""
    return f"{site_name(url)}_{endpoint_name(url)}_{stamp()}"


def shot_stem(url: str, name: str = "") -> str:
    """截图的文件主干：``[<自定义前缀>_]<站点名>_<时间戳>``。"""
    prefix = _sanitize(name)
    base = f"{site_name(url)}_{stamp()}"
    return f"{prefix}_{base}" if prefix else base
