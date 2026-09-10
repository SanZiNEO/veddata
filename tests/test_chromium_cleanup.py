"""chromium.py：生命周期相关的回归测试（不需要真浏览器）。

覆盖两个真 bug：
1. 启动失败**不能重试**（profile 被占用时重试 = 多开窗口）
2. 关浏览器要能**真关**（按档案里的 pid），而 detach 不能把档案删掉
"""

from __future__ import annotations

import pytest

from veddata import chromium


class FakeProc:
    pid = 4242

    def poll(self):
        return 1                     # 立刻退出（例如 profile 被另一个 Chrome 占着）

    def terminate(self):
        pass

    def wait(self, timeout=None):
        pass

    def kill(self):
        pass


def test_ensure_fails_fast_without_retry(monkeypatch, tmp_path):
    launches = {"count": 0}

    def fake_popen(*args, **kwargs):
        launches["count"] += 1
        return FakeProc()

    monkeypatch.setattr(chromium.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(chromium, "free_port", lambda: 12345)
    monkeypatch.setattr(chromium, "alive", lambda *a, **k: False)

    launcher = chromium.Launcher(path="c:/chrome.exe")
    with pytest.raises(chromium.ChromiumError) as excinfo:
        launcher.ensure(tmp_path, headless=False)

    assert launches["count"] == 1                    # 关键：只起一次
    message = str(excinfo.value)
    assert "profile" in message and str(tmp_path) in message   # 事实里带上 profile 路径
    assert launcher.started is False


def test_ensure_reuses_running_instance(monkeypatch, tmp_path):
    chromium.write_port_file(tmp_path, 9333, pid=42)
    monkeypatch.setattr(chromium, "alive", lambda *a, **k: True)
    launcher = chromium.Launcher(path="c:/chrome.exe")
    assert launcher.ensure(tmp_path, headless=False) == "http://127.0.0.1:9333"
    assert launcher.started is False


def test_read_pid(tmp_path):
    assert chromium.read_pid(tmp_path) == 0
    chromium.write_port_file(tmp_path, 9, pid=777)
    assert chromium.read_pid(tmp_path) == 777


def test_close_running_kills_recorded_pid(monkeypatch, tmp_path):
    chromium.write_port_file(tmp_path, 9222, pid=999)
    killed: dict = {}
    monkeypatch.setattr(chromium, "kill_tree", lambda pid: killed.update(pid=pid) or True)

    result = chromium.close_running(tmp_path)

    assert result == {"port": 9222, "pid": 999, "killed": True}
    assert killed["pid"] == 999
    assert chromium.read_port_file(tmp_path) is None       # 关完就把档案清了


def test_close_running_reports_not_running(monkeypatch, tmp_path):
    chromium.write_port_file(tmp_path, 9222, pid=999)
    monkeypatch.setattr(chromium, "kill_tree", lambda pid: False)
    assert chromium.close_running(tmp_path)["killed"] is False
    assert chromium.read_port_file(tmp_path) is None


def test_stop_detach_keeps_port_file(tmp_path):
    chromium.write_port_file(tmp_path, 9333, pid=1)
    launcher = chromium.Launcher(path="c:/chrome.exe")

    launcher.stop(tmp_path, clear=False)                   # detach：只断开
    assert chromium.read_port_file(tmp_path) == 9333       # 档案必须留着，否则下次会另起一个

    launcher.stop(tmp_path)                                # 真关：删档案
    assert chromium.read_port_file(tmp_path) is None
