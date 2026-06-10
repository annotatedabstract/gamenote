"""Optional self-update via the GitHub Releases API.

A lightweight version check (stdlib ``urllib``, no dependency) against the repo's
latest release. If a newer version exists, the app offers a one-click install:
download the release's installer and run it. The app quits so its files unlock;
the per-user Inno installer (same AppId) updates in place, no admin needed.

An opt-in "dev" channel (``global.update_channel``) instead tracks the rolling
``dev`` prerelease that CI republishes on every green push to main, comparing
this build's stamped commit (``build_info.json``) against the published one.

Only the frozen build can self-install; from source the install action just opens
the releases page. All network work is best-effort and never raises into the UI.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import __version__

log = logging.getLogger("gamenote.updater")

REPO = "annotatedabstract/gamenote"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
DEV_RELEASES_URL = f"https://github.com/{REPO}/releases/tag/dev"
_API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
_API_DEV = f"https://api.github.com/repos/{REPO}/releases/tags/dev"
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
    def __init__(
        self,
        version: str,
        tag: str,
        url: str,
        name: str,
        size: int,
        notes: str,
        channel: str = "stable",
    ) -> None:
        self.version = version
        self.tag = tag
        self.url = url  # installer asset download URL
        self.name = name
        self.size = size  # expected byte size, for an integrity check
        self.notes = notes
        self.channel = channel  # "stable" or "dev"


def _fetch_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _installer_asset(data: dict) -> tuple[str, str, int]:
    """(url, name, size) of a release's first trusted .exe asset, or ("", "", 0)."""
    for asset in data.get("assets", []):
        asset_name = str(asset.get("name", ""))
        if asset_name.lower().endswith(".exe"):
            candidate = str(asset.get("browser_download_url", ""))
            try:
                _require_trusted_url(candidate)
            except ValueError as e:
                log.warning("Ignoring update asset: %s", e)
                continue
            return candidate, asset_name, int(asset.get("size", 0) or 0)
    return "", "", 0


def check_latest(timeout: float = 10.0) -> UpdateInfo | None:
    """Fetch the latest release and return UpdateInfo if it is newer than the
    running version, or None if the running version is already current (or a
    newer release carries no usable installer asset).

    Raises on a transport or decode failure (offline, timeout, rate-limited,
    malformed response) so the caller can tell "could not check" apart from
    "up to date", which both used to collapse into None."""
    data = _fetch_json(_API_LATEST, timeout)

    tag = str(data.get("tag_name", ""))
    if parse_version(tag) <= parse_version(current_version()):
        return None

    url, name, size = _installer_asset(data)
    if not url:
        log.info("Newer release %s has no usable .exe asset; skipping.", tag)
        return None

    version = ".".join(str(p) for p in parse_version(tag))
    return UpdateInfo(
        version=version, tag=tag, url=url, name=name, size=size, notes=str(data.get("body", ""))
    )


def _build_info_path() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)  # one-folder build: the _internal dir
    if meipass:
        return Path(meipass) / "build_info.json"
    return Path(__file__).resolve().parent.parent / "build_info.json"  # repo root


def build_info() -> dict:
    """This build's identity ({commit, built_at, version}), stamped by
    packaging/build.sh and bundled by the spec. {} from an unstamped source
    tree or on any read/parse error (the dev channel treats that as
    "identity unknown")."""
    try:
        data = json.loads(_build_info_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# Machine-readable lines in the dev release body, written by CI. The \s* before
# the MULTILINE $ also eats a \r, so a CRLF-normalized body parses fine.
_COMMIT_RE = re.compile(r"^commit:\s*([0-9a-f]{40})\s*$", re.MULTILINE)
_BUILT_AT_RE = re.compile(r"^built_at:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s*$", re.MULTILINE)
_ISO_FULL_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def _parse_dev_body(body: str) -> tuple[str | None, str | None]:
    """(commit, built_at) parsed from a dev release body, each None if absent."""
    cm = _COMMIT_RE.search(body or "")
    bm = _BUILT_AT_RE.search(body or "")
    return (cm.group(1) if cm else None), (bm.group(1) if bm else None)


def check_dev(timeout: float = 10.0) -> UpdateInfo | None:
    """Fetch the rolling ``dev`` prerelease and return UpdateInfo when it
    carries a build we are not already running, or None when there is nothing
    (new) to offer. Raises on transport failures like :func:`check_latest`,
    except a 404 (no dev release has ever been published)."""
    try:
        data = _fetch_json(_API_DEV, timeout)
    except urllib.error.HTTPError as e:
        if e.code == 404:  # no dev build published yet (or the release was removed)
            log.info("No dev release exists; nothing to offer.")
            return None
        raise
    body = str(data.get("body", ""))
    commit, built_at = _parse_dev_body(body)
    if not commit or not built_at:
        log.info("Dev release body lacks commit/built_at lines; skipping.")
        return None
    own = build_info()
    own_commit = str(own.get("commit") or "")
    own_built_at = str(own.get("built_at") or "")
    if own_commit and own_commit == commit:
        return None  # already running this exact build
    # Fixed-format UTC stamps compare lexicographically == chronologically.
    # Guard only when our own stamp is well-formed; unknown identity always
    # offers (self-heals after the first dev install).
    if _ISO_FULL_RE.fullmatch(own_built_at) and built_at <= own_built_at:
        return None  # stale body / older build; never downgrade silently
    url, name, size = _installer_asset(data)
    if not url:
        log.info("Dev release has no usable .exe asset; skipping.")
        return None
    return UpdateInfo(
        version=f"dev {commit[:7]}",
        tag="dev",
        url=url,
        name=name,
        size=size,
        notes=body,
        channel="dev",
    )


def check_for_update(channel: str = "stable", timeout: float = 10.0) -> UpdateInfo | None:
    """Channel dispatch: "dev" tracks the rolling prerelease; anything else
    (including junk from a hand-edited config) means stable."""
    if str(channel).lower() == "dev":
        return check_dev(timeout)
    return check_latest(timeout)


def _require_trusted_url(url: str) -> None:
    """Reject anything that isn't an HTTPS URL on a GitHub host before we download
    and run it. The installer is fetched over TLS from GitHub; this refuses an
    http:// or off-host URL that a tampered/compromised API response could supply."""
    parts = urllib.parse.urlparse(url)
    host = (parts.hostname or "").lower()
    trusted = host == "github.com" or host.endswith((".github.com", ".githubusercontent.com"))
    if parts.scheme != "https" or not trusted:
        raise ValueError(f"untrusted download URL: {url!r}")


def download(
    url: str, expected_size: int | None = None, progress_cb=None, timeout: float = 30.0
) -> Path:
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

    available = Signal(object)  # UpdateInfo
    up_to_date = Signal(bool)  # manual? (True if the user asked)
    failed = Signal(bool, str)  # manual?, message
    progress = Signal(int, int)  # done, total
    ready = Signal(str)  # downloaded installer path

    def check_async(self, manual: bool = False, channel: str = "stable") -> None:
        threading.Thread(target=self._check, args=(manual, channel), daemon=True).start()

    def _check(self, manual: bool, channel: str = "stable") -> None:
        try:
            info = check_for_update(channel)
        except Exception as e:  # offline, timeout, rate-limited, malformed response
            log.info("Update check could not complete: %s", e)
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
            path = download(
                info.url, expected_size=info.size, progress_cb=lambda d, t: self.progress.emit(d, t)
            )
        except Exception as e:
            log.error("Update download failed: %s", e)
            self.failed.emit(True, str(e))
            return
        self.ready.emit(str(path))
