import json
from unittest import mock

from gamenote import updater


def test_parse_version():
    assert updater.parse_version("v1.2.3") == (1, 2, 3)
    assert updater.parse_version("1.1") == (1, 1, 0)
    assert updater.parse_version("v2") == (2, 0, 0)
    assert updater.parse_version("") == (0, 0, 0)


def _fake_urlopen(payload):
    body = json.dumps(payload).encode("utf-8")
    resp = mock.MagicMock()
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return lambda *a, **k: resp


def test_check_latest_returns_info_when_newer(monkeypatch):
    payload = {
        "tag_name": "v9.9.9",
        "body": "notes",
        "assets": [{"name": "gamenote-setup-9.9.9.exe",
                    "browser_download_url": "https://example/gamenote-setup-9.9.9.exe"}],
    }
    monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(payload))
    info = updater.check_latest()
    assert info is not None
    assert info.version == "9.9.9"
    assert info.url.endswith("gamenote-setup-9.9.9.exe")


def test_check_latest_none_when_not_newer(monkeypatch):
    payload = {"tag_name": "v0.0.1",
               "assets": [{"name": "x.exe", "browser_download_url": "u"}]}
    monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(payload))
    assert updater.check_latest() is None


def test_check_latest_none_without_exe_asset(monkeypatch):
    payload = {"tag_name": "v9.9.9",
               "assets": [{"name": "notes.txt", "browser_download_url": "u"}]}
    monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(payload))
    assert updater.check_latest() is None


def test_check_latest_none_on_network_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    assert updater.check_latest() is None
