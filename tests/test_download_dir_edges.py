"""下载目录解析的两个边界（用户提的）：

1. 偏好里开着"每次询问保存位置"（prompt_for_download）→ 路径由用户每次现选，
   我们必须返回 None（绝不能替他设 downloadPath）
2. 非 Windows：读 XDG 的 XDG_DOWNLOAD_DIR，而不是硬退到 ~/Downloads
"""

from __future__ import annotations

import json

from veddata import downloads


def test_prompt_for_download_means_unknown(tmp_path):
    (tmp_path / "Default").mkdir()
    (tmp_path / "Default" / "Preferences").write_text(
        json.dumps({"download": {"prompt_for_download": True,
                                 "default_directory": r"E:\Downloads"}}), encoding="utf-8")
    assert downloads.download_dir(tmp_path) is None      # 每次问 → 不设路径


def test_preferences_directory_wins(tmp_path):
    (tmp_path / "Default").mkdir()
    (tmp_path / "Default" / "Preferences").write_text(
        json.dumps({"download": {"default_directory": r"E:\MyDL"}}), encoding="utf-8")
    assert str(downloads.download_dir(tmp_path)) == r"E:\MyDL"


def test_xdg_download_dir_is_read(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    target = tmp_path / "下载"
    target.mkdir()
    (config / "user-dirs.dirs").write_text(
        f'XDG_DOWNLOAD_DIR="{target}"\n', encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    assert downloads._xdg_downloads() == target


def test_xdg_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "nope"))
    assert downloads._xdg_downloads() is None


def test_os_downloads_falls_back_to_home_downloads(monkeypatch, tmp_path):
    monkeypatch.setattr(downloads.sys, "platform", "darwin")     # 跳过 Windows/XDG 分支
    monkeypatch.setattr(downloads.Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / "Downloads").mkdir()
    assert downloads.os_downloads_dir() == tmp_path / "Downloads"


def test_os_downloads_none_when_nothing_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(downloads.sys, "platform", "darwin")
    monkeypatch.setattr(downloads.Path, "home", classmethod(lambda cls: tmp_path))
    assert downloads.os_downloads_dir() is None
