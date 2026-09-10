"""downloads.py：下载事实的模型测试（不需要浏览器）。

用户定下的模型：
- 有下载才说，没有就不加
- 中间态（inProgress）实时拉、不消费
- 结束态（completed / canceled）进队列，**下一次调用带出去、发完即清**
- 按 guid 去重，队列有上限
"""

from __future__ import annotations

import json

import pytest

from veddata import downloads


@pytest.fixture(autouse=True)
def _clean():
    downloads.reset()
    yield
    downloads.reset()


def _begin(guid="g1", name="a.svg", url="https://x/a.svg"):
    downloads.on_will_begin({"guid": guid, "suggestedFilename": name, "url": url})


def _progress(guid="g1", state="completed", received=4300, total=4300):
    downloads.on_progress({"guid": guid, "state": state,
                           "receivedBytes": received, "totalBytes": total})


def test_nothing_when_no_download():
    assert downloads.render() == []
    assert downloads.append_facts("plain output") == "plain output"


def test_completed_is_reported_once_then_cleared():
    downloads._download_dir = downloads.Path("/dst")
    _begin()
    _progress()
    lines = downloads.take_lines()
    assert len(lines) == 1 and "a.svg" in lines[0] and "completed" in lines[0]
    assert str(downloads.Path("/dst") / "a.svg") in lines[0]
    assert downloads.take_lines() == []            # 一次性消费：发完就清


def test_in_progress_is_live_not_consumed():
    downloads._download_dir = downloads.Path("/dst")
    _begin()
    _progress(state="inProgress", received=3100, total=4200)
    first = downloads.take_lines()
    second = downloads.take_lines()
    assert first and "in progress" in first[0] and "3.0 KB/4.1 KB" in first[0]
    assert second == first                          # 中间态不消费，下次调用照样实时报


def test_canceled_is_reported():
    downloads._download_dir = downloads.Path("/dst")
    _begin(name="broken.svg")
    _progress(state="canceled", received=10, total=0)
    assert any("canceled" in line for line in downloads.take_lines())


def test_guid_is_deduped():
    downloads._download_dir = downloads.Path("/dst")
    _begin()
    _progress(state="completed", received=10, total=10)
    _progress(state="completed", received=10, total=10)
    assert len(downloads.render()) == 1


def test_queue_is_capped():
    downloads._download_dir = downloads.Path("/dst")
    for index in range(14):
        _begin(guid=f"g{index}", name=f"f{index}.svg")
        _progress(guid=f"g{index}")
    assert len(downloads.render()) == downloads.MAX_QUEUE


def test_append_facts_keeps_original_output():
    downloads._download_dir = downloads.Path("/dst")
    _begin()
    _progress()
    text = downloads.append_facts("clicked 'Download'")
    assert text.startswith("clicked 'Download'")
    assert "download: a.svg" in text


def test_download_dir_reads_profile_preferences(tmp_path):
    (tmp_path / "Default").mkdir()
    (tmp_path / "Default" / "Preferences").write_text(
        json.dumps({"download": {"default_directory": r"E:\Downloads"}}), encoding="utf-8")
    assert str(downloads.download_dir(tmp_path)) == r"E:\Downloads"


def test_download_dir_falls_back_to_os_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(downloads, "os_downloads_dir", lambda: downloads.Path(r"E:\Downloads"))
    assert str(downloads.download_dir(tmp_path)) == r"E:\Downloads"


def test_download_dir_unknown_returns_none(tmp_path, monkeypatch):
    """读不到就不猜：返回 None（调用方不会给浏览器设 downloadPath，文件不挪）。"""
    monkeypatch.setattr(downloads, "os_downloads_dir", lambda: None)
    assert downloads.download_dir(tmp_path) is None
