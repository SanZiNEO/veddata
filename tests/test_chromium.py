"""chromium.py：启动参数与"复用已有实例"的纯逻辑测试（不需要真的开浏览器）。"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from veddata import chromium


def test_build_args_keeps_automation_switches_out(tmp_path):
    args = chromium.build_args(r"C:\chrome.exe", 9222, tmp_path, headless=False)
    joined = " ".join(args)
    assert args[0] == r"C:\chrome.exe"
    assert "--remote-debugging-port=9222" in args
    assert f"--user-data-dir={tmp_path}" in args
    # 这三样是 Playwright 那一套的特征，必须一个都不能有
    assert "--enable-automation" not in joined
    assert "--remote-debugging-pipe" not in joined
    assert "--disable-blink-features" not in joined
    # 不传 URL，让浏览器停在空白页
    assert not any(item.startswith("http") for item in args)


def test_build_args_headless_only_when_asked(tmp_path):
    assert "--headless=new" not in chromium.build_args("c.exe", 1, tmp_path, headless=False)
    assert "--headless=new" in chromium.build_args("c.exe", 1, tmp_path, headless=True)


def test_browser_path_honours_explicit_executable(tmp_path, monkeypatch):
    fake = tmp_path / "my-chrome.exe"
    fake.write_bytes(b"")
    monkeypatch.setenv("BROWSER_PATH", str(fake))
    assert chromium.browser_path() == str(fake)


def test_browser_path_falls_back_to_autodetect(tmp_path, monkeypatch):
    monkeypatch.setenv("BROWSER_PATH", "chrome")
    found = chromium.browser_path()          # 本机有 Chrome/Edge 时非 None；没有则 None
    assert found is None or isinstance(found, str)


def test_port_file_roundtrip(tmp_path):
    assert chromium.read_port_file(tmp_path) is None
    chromium.write_port_file(tmp_path, 9333, pid=42)
    assert chromium.read_port_file(tmp_path) == 9333
    payload = json.loads((tmp_path / chromium.PORT_FILE).read_text(encoding="utf-8"))
    assert payload["pid"] == 42
    chromium.clear_port_file(tmp_path)
    assert chromium.read_port_file(tmp_path) is None


def test_alive_is_false_for_dead_port():
    port = chromium.free_port()
    assert chromium.alive(port, timeout=0.5) is False


def test_free_port_is_usable_range():
    assert 0 < chromium.free_port() < 65536


class _CdpStub(BaseHTTPRequestHandler):
    def log_message(self, *args):                                              # noqa: A003
        pass

    def do_GET(self):                                                          # noqa: N802
        if self.path == "/json/version":
            body = json.dumps({"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/x"}).encode()
        else:
            body = b"{}"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def fake_cdp():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CdpStub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_port
    server.shutdown()


def test_launcher_reuses_running_instance(tmp_path, fake_cdp):
    """profile 里记着端口、那个实例还活着 → 直接复用，不再起新的。"""
    chromium.write_port_file(tmp_path, fake_cdp)
    launcher = chromium.Launcher(path=r"C:\does-not-exist\chrome.exe")
    address = launcher.ensure(tmp_path, headless=True)
    assert address == f"http://127.0.0.1:{fake_cdp}"
    assert launcher.started is False
    assert launcher.process is None


def test_launcher_raises_when_no_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(chromium, "browser_path", lambda: None)
    launcher = chromium.Launcher(path=None)
    with pytest.raises(chromium.ChromiumError):
        launcher.ensure(tmp_path, headless=True)
