"""默认路径与目录配置的唯一真源。

配置面（**只有 CLI 参数，没有环境变量**）
--------------------------------------
``--profile-dir <绝对路径>``   浏览器 profile 目录（保留登录态）
``--response-dir <绝对路径>``  导出 / 截图落地目录

为什么不用环境变量：``args`` 是所有 MCP 客户端都有的唯一公共面（Claude Desktop、
Cursor、VS Code、DSH 的配置里都有），而 ``env`` 的传递各家并不一致。少一条通路就
少一套优先级和一份文档，也就少一处能出错的地方。旧版本那套 ``RESPONSE_DIR`` /
``USER_DATA_DIR`` / ``VEDDATA_WORKSPACE`` / ``VEDDATA_HOME`` 环境变量已全部移除，
不留兼容垫片。

默认落点
--------
``<用户数据根>/veddata/``（Windows ``%LOCALAPPDATA%`` / macOS ``Application Support``
/ Linux ``XDG_DATA_HOME``）::

    <用户数据根>/veddata/
    ├── profile/    浏览器 profile（未指定 --profile-dir 时的默认值）
    └── cache/      内部缓存（ved_fetch 的页面文本缓存，不可配置）

``response/`` 不再有默认值：导出/截图是**交付物**，落到哪必须由使用方明确指定。
没指定时，程序在**真要写盘的那一刻**报错（而不是启动就失败，连不写盘的工具一起
拖下水），并在错误里说明去 ``args`` 里加 ``--response-dir``。

路径规则
--------
- 只接受**绝对路径**（``~`` 会展开）；相对路径一律拒绝 —— 相对路径要按 CWD 解析，
  而各家 harness 是否设 CWD、设成什么都不同，等于把落点交给宿主决定。
- 目录不存在就创建；路径指向已存在的文件则报错。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIRNAME = "veddata"
PROFILE_DIRNAME = "profile"
CACHE_DIRNAME = "cache"

MISSING_RESPONSE_DIR_HINT = (
    "未配置输出目录：请在 MCP 配置的 args 里加上 "
    "--response-dir <绝对路径>，或本次调用传 output_dir。"
)

_profile_dir: Path | None = None
_response_dir: Path | None = None


class PathError(ValueError):
    """路径配置有问题（相对路径、指向文件、无法创建等）。"""


def data_home() -> Path:
    """用户级数据根目录（按平台约定推导，无环境变量开关）。"""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / APP_DIRNAME


def cache_dir() -> Path:
    """内部缓存目录（ved_fetch 的页面文本缓存）。不属于交付物，不可配置。"""
    return data_home() / CACHE_DIRNAME


def profile_dir() -> Path:
    """浏览器 profile 目录：``--profile-dir`` 指定的那个，否则数据根下的 ``profile/``。"""
    return _profile_dir or (data_home() / PROFILE_DIRNAME)


def set_profile_dir(value: str | os.PathLike) -> None:
    """记录 ``--profile-dir``（原样保存，写入时报错交给 prepare_dir）。"""
    global _profile_dir
    _profile_dir = Path(str(value))


def response_dir() -> Path | None:
    """导出 / 截图落地目录：``--response-dir`` 指定的那个；**未配置返回 None**。"""
    return _response_dir


def set_response_dir(value: str | os.PathLike) -> None:
    """记录 ``--response-dir``（原样保存，写入时报错交给 prepare_dir）。"""
    global _response_dir
    _response_dir = Path(str(value))


def prepare_dir(raw: str | os.PathLike, *, what: str = "输出目录") -> Path:
    """校验并准备一个**绝对**目录：展开 ``~``、拒绝相对路径、不存在则创建。

    Raises:
        PathError: 相对路径 / 指向已存在的文件 / 无法创建。
    """
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        raise PathError(f"{what}必须是绝对路径，收到：{raw}")
    if path.exists() and not path.is_dir():
        raise PathError(f"{what}指向的是一个文件，不是目录：{path}")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PathError(f"{what}无法创建或写入：{path}（{exc}）") from exc
    return path


def resolve_response_dir(output_dir: str | os.PathLike | None = None) -> Path:
    """本次写盘要落的目录：调用参数 > ``--response-dir``；都没有则报错。

    Raises:
        PathError: 未配置（``MISSING_RESPONSE_DIR_HINT``）或路径非法。
    """
    target = output_dir or _response_dir
    if target is None:
        raise PathError(MISSING_RESPONSE_DIR_HINT)
    return prepare_dir(target, what="输出目录")


def describe() -> str:
    """路径摘要，便于排查（stdio 服务只能往 stderr 打，勿 print 到 stdout）。"""
    return (
        f"profile={profile_dir()} "
        f"response={_response_dir or '(未配置 --response-dir：写盘时报错)'} "
        f"cache={cache_dir()}"
    )
