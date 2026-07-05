import hashlib
import json
import sys
import urllib.error
from unittest import mock

import pytest

from gamenote import updater

# Qt signals need an application instance; the shared session-scoped ``qapp``
# fixture (tests/conftest.py) provides it.


def test_parse_version():
    assert updater.parse_version("v1.2.3") == (1, 2, 3)
    assert updater.parse_version("1.1") == (1, 1, 0)
    assert updater.parse_version("v2") == (2, 0, 0)
    assert updater.parse_version("") == (0, 0, 0)
    # A suffix contributes nothing ("3-rc1" once concatenated digits into 31).
    assert updater.parse_version("1.2.3-rc1") == (1, 2, 3)
    assert updater.parse_version("1.4.0-dev.abc123") == (1, 4, 0)
    assert updater.parse_version("dev") == (0, 0, 0)


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
        "assets": [
            {
                "name": "gamenote-setup-9.9.9.exe",
                "size": 123,
                "digest": f"sha256:{'a' * 64}",
                "browser_download_url": "https://github.com/annotatedabstract/gamenote/releases/"
                "download/v9.9.9/gamenote-setup-9.9.9.exe",
            }
        ],
    }
    monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(payload))
    info = updater.check_latest()
    assert info is not None
    assert info.version == "9.9.9"
    assert info.url.endswith("gamenote-setup-9.9.9.exe")
    assert info.size == 123
    assert info.sha256 == "a" * 64


def test_asset_sha256_parses_and_rejects():
    assert updater._asset_sha256({"digest": f"sha256:{'A' * 64}"}) == "a" * 64  # normalized
    assert updater._asset_sha256({"digest": f"sha1:{'a' * 40}"}) == ""  # wrong algorithm
    assert updater._asset_sha256({"digest": "sha256:nothex"}) == ""
    assert updater._asset_sha256({"digest": f"sha256:{'a' * 63}"}) == ""  # wrong length
    assert updater._asset_sha256({}) == ""  # pre-digest asset: size check only


def test_check_latest_none_when_not_newer(monkeypatch):
    payload = {"tag_name": "v0.0.1", "assets": [{"name": "x.exe", "browser_download_url": "u"}]}
    monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(payload))
    assert updater.check_latest() is None


def test_check_latest_none_without_exe_asset(monkeypatch):
    payload = {"tag_name": "v9.9.9", "assets": [{"name": "notes.txt", "browser_download_url": "u"}]}
    monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(payload))
    assert updater.check_latest() is None


def test_check_latest_raises_on_network_error(monkeypatch):
    # A transport failure must propagate so the caller can distinguish it from
    # "up to date" (both used to collapse into None).
    def boom(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    with pytest.raises(OSError):
        updater.check_latest()


class _FakeResp:
    def __init__(self, data: bytes):
        self._data = data
        self._sent = False
        self.headers = {"Content-Length": str(len(data))}

    def read(self, n: int = -1) -> bytes:
        if self._sent:
            return b""
        self._sent = True
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_GH_URL = "https://github.com/annotatedabstract/gamenote/releases/download/v9/setup.exe"


def test_download_writes_file_and_passes_size_check(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _FakeResp(b"abcd"))
    path = updater.download(_GH_URL, expected_size=4)
    assert path.read_bytes() == b"abcd"
    assert path.name == "gamenote-setup.exe"  # fixed, sanitized name
    assert not (tmp_path / "gamenote-setup.exe.part").exists()  # part renamed away


def test_download_raises_on_size_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _FakeResp(b"abcd"))
    with pytest.raises(OSError):
        updater.download(_GH_URL, expected_size=999)
    assert not (tmp_path / "gamenote-setup.exe.part").exists()  # partial cleaned up


def test_download_verifies_sha256(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _FakeResp(b"abcd"))
    good = hashlib.sha256(b"abcd").hexdigest()
    path = updater.download(_GH_URL, expected_size=4, expected_sha256=good.upper())
    assert path.read_bytes() == b"abcd"  # case-insensitive match passes


def test_download_raises_on_sha256_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _FakeResp(b"abcd"))
    with pytest.raises(OSError, match="sha256"):
        updater.download(_GH_URL, expected_size=4, expected_sha256="0" * 64)
    assert not (tmp_path / "gamenote-setup.exe.part").exists()  # partial cleaned up
    assert not (tmp_path / "gamenote-setup.exe").exists()  # nothing runnable left


def test_download_without_digest_keeps_size_check_only(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _FakeResp(b"abcd"))
    path = updater.download(_GH_URL, expected_size=4, expected_sha256="")
    assert path.read_bytes() == b"abcd"


def test_download_rejects_untrusted_url(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    with pytest.raises(ValueError):
        updater.download("http://github.com/o/r/setup.exe")  # not https
    with pytest.raises(ValueError):
        updater.download("https://evil.example/setup.exe")  # not a GitHub host


def test_check_emits_failed_when_offline(qapp, monkeypatch):
    def boom(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    up = updater.Updater()
    seen: dict[str, object] = {}
    up.failed.connect(lambda manual, msg: seen.update(failed=manual))
    up.up_to_date.connect(lambda manual: seen.update(up_to_date=manual))
    up._check(manual=True)
    assert seen == {"failed": True}  # offline is a failure, not "up to date"


def test_check_emits_up_to_date_when_current(qapp, monkeypatch):
    payload = {"tag_name": "v0.0.1", "assets": []}  # older than the running version
    monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(payload))
    up = updater.Updater()
    seen: dict[str, object] = {}
    up.failed.connect(lambda manual, msg: seen.update(failed=manual))
    up.up_to_date.connect(lambda manual: seen.update(up_to_date=manual))
    up._check(manual=True)
    assert seen == {"up_to_date": True}


# --- dev channel ------------------------------------------------------------

_DEV_SHA = "a" * 40
_DEV_BODY = (
    "Automated development build from the latest push to main.\n"
    "\n"
    "Installed via the in-app update channel (Settings -> Updates -> Channel: "
    "Development builds). May be broken; to go back, switch the channel to "
    "Stable releases and reinstall the latest stable release.\n"
    "\n"
    f"commit: {_DEV_SHA}\n"
    "built_at: 2026-06-10T12:00:00Z\n"
    "version: 1.3.0\n"
)


def _dev_payload(body=_DEV_BODY, assets=None):
    if assets is None:
        assets = [
            {
                "name": "gamenote-setup-dev.exe",
                "size": 456,
                "browser_download_url": "https://github.com/annotatedabstract/gamenote/"
                "releases/download/dev/gamenote-setup-dev.exe",
            }
        ]
    return {"tag_name": "dev", "prerelease": True, "body": body, "assets": assets}


def test_parse_dev_body_parses_lf_and_crlf():
    for body in (_DEV_BODY, _DEV_BODY.replace("\n", "\r\n")):
        commit, built_at = updater._parse_dev_body(body)
        assert commit == _DEV_SHA
        assert built_at == "2026-06-10T12:00:00Z"


def test_parse_dev_body_missing_or_malformed():
    assert updater._parse_dev_body("") == (None, None)
    assert updater._parse_dev_body("just prose, no machine lines") == (None, None)
    short_sha = f"commit: {'a' * 39}\nbuilt_at: 2026-06-10T12:00:00Z\n"
    assert updater._parse_dev_body(short_sha) == (None, "2026-06-10T12:00:00Z")
    bad_date = f"commit: {_DEV_SHA}\nbuilt_at: yesterday\n"
    assert updater._parse_dev_body(bad_date) == (_DEV_SHA, None)


def test_build_info_reads_frozen_path(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    stamp = {"commit": _DEV_SHA, "built_at": "2026-06-10T12:00:00Z", "version": "1.3.0"}
    (tmp_path / "build_info.json").write_text(json.dumps(stamp), encoding="utf-8")
    assert updater._build_info_path() == tmp_path / "build_info.json"
    assert updater.build_info() == stamp


def test_build_info_missing_or_garbage(monkeypatch, tmp_path):
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(updater, "_build_info_path", lambda: missing)
    assert updater.build_info() == {}
    garbage = tmp_path / "garbage.json"
    garbage.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(updater, "_build_info_path", lambda: garbage)
    assert updater.build_info() == {}
    not_dict = tmp_path / "list.json"
    not_dict.write_text("[1, 2]", encoding="utf-8")
    monkeypatch.setattr(updater, "_build_info_path", lambda: not_dict)
    assert updater.build_info() == {}


def test_check_dev_offers_when_commit_differs(monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(_dev_payload()))
    monkeypatch.setattr(
        updater, "build_info", lambda: {"commit": "b" * 40, "built_at": "2026-06-01T00:00:00Z"}
    )
    info = updater.check_dev()
    assert info is not None
    assert info.version == f"dev {_DEV_SHA[:7]}"
    assert info.tag == "dev"
    assert info.channel == "dev"
    assert info.size == 456
    assert info.url.endswith("gamenote-setup-dev.exe")


def test_check_dev_none_when_same_commit(monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(_dev_payload()))
    monkeypatch.setattr(
        updater, "build_info", lambda: {"commit": _DEV_SHA, "built_at": "2026-06-10T12:00:00Z"}
    )
    assert updater.check_dev() is None


def test_check_dev_none_on_downgrade(monkeypatch):
    # A different commit whose published build is not newer than ours must not
    # be offered (stale body or a re-published older build).
    monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(_dev_payload()))
    for own_built_at in ("2026-06-10T12:00:00Z", "2026-06-11T00:00:00Z"):
        monkeypatch.setattr(
            updater, "build_info", lambda at=own_built_at: {"commit": "b" * 40, "built_at": at}
        )
        assert updater.check_dev() is None


def test_check_dev_offers_when_own_identity_unknown(monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(_dev_payload()))
    monkeypatch.setattr(updater, "build_info", lambda: {})
    info = updater.check_dev()
    assert info is not None and info.channel == "dev"


def test_check_dev_none_when_body_lacks_fields(monkeypatch):
    payload = _dev_payload(body="hand-edited prose with no machine lines")
    monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(payload))
    monkeypatch.setattr(updater, "build_info", lambda: {})
    assert updater.check_dev() is None


def test_check_dev_none_without_usable_asset(monkeypatch):
    monkeypatch.setattr(updater, "build_info", lambda: {})
    no_exe = _dev_payload(assets=[{"name": "notes.txt", "browser_download_url": "u"}])
    monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(no_exe))
    assert updater.check_dev() is None
    untrusted = _dev_payload(
        assets=[{"name": "x.exe", "size": 1, "browser_download_url": "https://evil.example/x.exe"}]
    )
    monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(untrusted))
    assert updater.check_dev() is None


def test_check_dev_404_means_no_update(monkeypatch):
    def gone(*a, **k):
        raise urllib.error.HTTPError("u", 404, "Not Found", None, None)

    monkeypatch.setattr(updater.urllib.request, "urlopen", gone)
    assert updater.check_dev() is None  # no dev release published yet

    def broken(*a, **k):
        raise urllib.error.HTTPError("u", 500, "Server Error", None, None)

    monkeypatch.setattr(updater.urllib.request, "urlopen", broken)
    with pytest.raises(urllib.error.HTTPError):
        updater.check_dev()


def test_check_for_update_dispatches_by_channel(monkeypatch):
    seen_urls: list[str] = []
    body = json.dumps({"tag_name": "v0.0.1", "assets": []}).encode("utf-8")

    def capture(req, *a, **k):
        seen_urls.append(req.full_url)
        resp = mock.MagicMock()
        resp.read.return_value = body
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        return resp

    monkeypatch.setattr(updater.urllib.request, "urlopen", capture)
    updater.check_for_update("dev")
    updater.check_for_update("stable")
    updater.check_for_update("weird")  # junk falls back to stable
    assert seen_urls == [updater._API_DEV, updater._API_LATEST, updater._API_LATEST]


def test_check_threads_channel_through(qapp, monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(_dev_payload()))
    monkeypatch.setattr(updater, "build_info", lambda: {})
    up = updater.Updater()
    seen: dict[str, object] = {}
    up.available.connect(lambda info: seen.update(channel=info.channel))
    up._check(manual=True, channel="dev")
    assert seen == {"channel": "dev"}
