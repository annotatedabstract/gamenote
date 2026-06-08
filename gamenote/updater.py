"""Optional self-update via the GitHub Releases API.

A lightweight version check (stdlib ``urllib``, no dependency) against the repo's
latest release. If a newer version exists, the app offers a one-click install:
download the release's installer and run it. The app quits so its files unlock;
the per-user Inno installer (same AppId) updates in place, no admin needed.

Only the frozen build can self-install; from source the install action just opens
the releases page. All network work is best-effort and never raises into the UI.
"""

from __future__ import annotations

import os
import sys
import json
import logging
import tempfile
import threading
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import __version__

log = logging.getLogger("gamenote.updater")

REPO = "annotatedabstract/gamenote"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
_API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
_HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "gamenote-updater"}


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def current_version() -> str:
    return __version__


def parse_version(s: str) -> tuple[int, int, int]:
    """'v1.2.3' or '1.2' -> (1, 2, 3). Non-numeric junk is ignored."""
    s = (s or "").strip().lstrip("vV")
    parts: list[int] = []
    for piece in s.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


class UpdateInfo:
    def __init__(self, version: str, tag: str, url: str, name: str, size: int, notes: str) -> None:
        self.version = version
        self.tag = tag
        self.url = url      # installer asset download URL
        self.name = name
        self.size = size    # expected byte size, for an integrity check
        self.notes = notes


def check_latest(timeout: float = 10.0) -> UpdateInfo | None:
    """Return UpdateInfo if the latest release is newer than the running version,
    else None (also None on any error: offline, rate-limited, no asset)."""
    try:
        req = urllib.request.Request(_API_LATEST, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log.info("Update check failed: %s", e)
        return None

    tag = str(data.get("tag_name", ""))
    if parse_version(tag) <= parse_version(current_version()):
        return None

    url = name = ""
    size = 0
    for asset in data.get("assets", []):
        asset_name = str(asset.get("name", ""))
        if asset_name.lower().endswith(".exe"):
            candidate = str(asset.get("browser_download_url", ""))
            try:
                _require_trusted_url(candidate)
            except ValueError as e:
                log.warning("Ignoring update asset: %s", e)
                continue
            url = candidate
            name = asset_name
            size = int(asset.get("size", 0) or 0)
            break
    if not url:
        log.info("Newer release %s has no usable .exe asset; skipping.", tag)
        return None

    version = ".".join(str(p) for p in parse_version(tag))
    return UpdateInfo(version=version, tag=tag, url=url, name=name, size=size,
                      notes=str(data.get("body", "")))


def _require_trusted_url(url: str) -> None:
    """Reject anything that isn't an HTTPS URL on a GitHub host before we download
    and run it. The installer is fetched over TLS from GitHub; this refuses an
    http:// or off-host URL that a tampered/compromised API response could supply."""
    parts = urllib.parse.urlparse(url)
    host = (parts.hostname or "").lower()
    trusted = host == "github.com" or host.endswith((".github.com", ".githubusercontent.com"))
    if parts.scheme != "https" or not trusted:
        raise ValueError(f"untrusted download URL: {url!r}")


def download(url: str, expected_size: int | None = None, progress_cb=None,
             timeout: float = 30.0) -> Path:
    """Download ``url`` (must be an HTTPS GitHub URL) to a fixed temp path and
    return it. Writes to a ``.part`` file and atomically renames on success;
    ``progress_cb`` (if given) gets (bytes_done, bytes_total). If ``expected_size``
    is set and the finished file does not match, raises (guards a truncated
    download). The partial file is removed on any failure."""
    _require_trusted_url(url)
    dest = Path(tempfile.gettempdir()) / "gamenote-setup.exe"
    part = dest.with_suffix(".exe.part")
    req = urllib.request.Request(url, headers={"User-Agent": "gamenote-updater"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(part, "wb") as f:
            total = int(resp.headers.get("Content-Length", 0) or 0) or (expected_size or 0)
            done = 0
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb is not None and total:
                    progress_cb(done, total)

        actual = part.stat().st_size
        if expected_size and actual != expected_size:
            raise OSError(f"download size mismatch: got {actual}, expected {expected_size}")
        os.replace(part, dest)  # atomic; only a complete download becomes the .exe
        return dest
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise


def run_installer(path: str) -> None:
    """Launch the installer detached (so it can replace files after we exit)."""
    os.startfile(str(path))  # noqa: S606 - Windows shell-launch of a trusted setup.exe


class Updater(QObject):
    """Qt wrapper that runs the checks/downloads off-thread and reports back via
    queued signals (safe to connect to main-thread slots)."""

    available = Signal(object)       # UpdateInfo
    up_to_date = Signal(bool)        # manual? (True if the user asked)
    failed = Signal(bool, str)       # manual?, message
    progress = Signal(int, int)      # done, total
    ready = Signal(str)              # downloaded installer path

    def check_async(self, manual: bool = False) -> None:
        threading.Thread(target=self._check, args=(manual,), daemon=True).start()

    def _check(self, manual: bool) -> None:
        try:
            info = check_latest()
        except Exception as e:  # defensive; check_latest already swallows
            self.failed.emit(manual, str(e))
            return
        if info is not None:
            self.available.emit(info)
        else:
            self.up_to_date.emit(manual)

    def download_async(self, info: UpdateInfo) -> None:
        threading.Thread(target=self._download, args=(info,), daemon=True).start()

    def _download(self, info: UpdateInfo) -> None:
        try:
            path = download(info.url, expected_size=info.size,
                            progress_cb=lambda d, t: self.progress.emit(d, t))
        except Exception as e:
            log.error("Update download failed: %s", e)
            self.failed.emit(True, str(e))
            return
        self.ready.emit(str(path))
