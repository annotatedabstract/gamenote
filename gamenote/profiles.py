"""Profiles, the destination resolver, and the line-format renderer.

A profile decides where a note goes and how the appended line looks. The model
and all capture/VAD tuning stay global; a profile is purely about destination
and format.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any

# Characters Windows forbids in a path component, plus we trim trailing dots and
# spaces (also illegal at the end of a Windows name).
_INVALID_CHARS = '<>:"/\\|?*'

# Windows reserved device names; a file named like one of these (with or without
# an extension) is special. Prefixing keeps a context like "CON" usable as a path.
_RESERVED_NAMES = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

# Where a note lands when {context} is used but the context is empty.
DEFAULT_PLACEHOLDER = "_Unsorted"


def sanitize_part(value: str) -> str:
    """Make ``value`` safe as a single Windows path component. Strips forbidden
    characters and control characters, then trailing dots and spaces, and guards
    Windows reserved device names. Returns an empty string if nothing survives
    (the caller decides on a fallback)."""
    cleaned = "".join(c for c in value if c not in _INVALID_CHARS and ord(c) >= 32)
    cleaned = cleaned.strip().rstrip(" .")
    if cleaned and cleaned.split(".", 1)[0].upper() in _RESERVED_NAMES:
        cleaned = "_" + cleaned
    return cleaned


def format_offset(seconds: float) -> str:
    """Seconds into a recording -> a compact offset string: ``MM:SS`` normally,
    ``H:MM:SS`` once past an hour (e.g. ``06:12``, ``1:03:45``). Negative values
    clamp to ``00:00``."""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _parse_sidecar_time(value: str) -> datetime | None:
    """Parse a sidecar timestamp. Accepts gamenote's ``%Y-%m-%d_%H-%M-%S`` plus a
    couple of ISO-ish forms. Returns None on anything unparseable."""
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d_%H-%M-%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


# How long to wait before re-reading a sidecar that looks caught mid-write.
# The OBS script's truncate-then-write is sub-millisecond, so this is generous
# while staying unnoticeable on the paths that read on the GUI thread (the tray
# tooltip and the settings preview, when the file is persistently empty).
_SIDECAR_RETRY_DELAY = 0.03


@dataclass(frozen=True)
class SidecarSnapshot:
    """One consistent read of a sidecar/context file: the parsed JSON object (or
    None when the content is not a JSON object) plus the raw text (or None when
    the file is missing/unreadable). Taking a single snapshot per note keeps all
    OBS-derived decoration -- session header, {clip}, file sub-header, game --
    consistent with each other even while OBS rewrites the file."""

    data: dict[str, Any] | None
    text: str | None

    def context_value(self) -> str:
        """The context (game) this file provides: the JSON ``game`` key, or the
        whole content for a plain-text file, or "" when missing/empty. Content
        that starts with ``{`` but did not parse is clearly a broken/truncated
        sidecar, never a game name, so it also yields "" rather than leaking a
        JSON fragment into note paths."""
        if self.data is not None:
            return str(self.data.get("game", "") or "").strip()
        if self.text is not None:
            stripped = self.text.strip()
            return "" if stripped.startswith("{") else stripped
        return ""


def _looks_mid_write(raw: str) -> bool:
    """True when a read looks like it caught OBS mid-write: the write truncates
    in place, so the reader can see an empty file or a JSON prefix that does not
    parse yet. A plain-text context value never matches (no retry cost there)."""
    stripped = raw.strip()
    if not stripped:
        return True
    if stripped.startswith("{"):
        try:
            json.loads(stripped)
        except ValueError:
            return True
    return False


def read_sidecar(path: str) -> SidecarSnapshot:
    """Read ``path`` once and parse it. The OBS script rewrites the sidecar in
    place (truncate + write), so an empty or partially-written JSON read is
    retried once after a short delay before being taken at face value."""
    if not path:
        return SidecarSnapshot(None, None)

    def _read() -> str | None:
        try:
            return Path(path).read_text(encoding="utf-8")
        except OSError:
            return None

    raw = _read()
    if raw is not None and _looks_mid_write(raw):
        time.sleep(_SIDECAR_RETRY_DELAY)
        retry = _read()
        if retry is not None:
            raw = retry

    if raw is None:
        return SidecarSnapshot(None, None)
    stripped = raw.strip()
    if not stripped:
        return SidecarSnapshot(None, "")
    try:
        data = json.loads(stripped)
    except ValueError:  # includes json.JSONDecodeError; plain-text value
        data = None
    return SidecarSnapshot(data if isinstance(data, dict) else None, raw)


@dataclass
class LineFormat:
    timestamp_format: str = "%Y-%m-%d %H:%M:%S"
    prefix: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> LineFormat:
        d = d or {}
        return cls(
            timestamp_format=d.get("timestamp_format", "%Y-%m-%d %H:%M:%S"),
            prefix=d.get("prefix", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"timestamp_format": self.timestamp_format, "prefix": self.prefix}


@dataclass
class Profile:
    id: str
    name: str
    hotkey: str
    dest_root: str
    path_template: str
    line_format: LineFormat = field(default_factory=LineFormat)
    use_session_headers: bool = True
    # Optional: read OBS recording info from a gamenote-obs.json sidecar (see
    # integrations/obs). Fills the {clip} token in the line prefix, names the
    # current recording file in a sub-header, and sources the session header
    # from the recording's start time.
    clip_from_file: bool = False
    clip_file: str = ""
    # Also source {context} (the sidecar's "game") from that same file,
    # overriding the global context for this profile.
    context_from_obs: bool = False
    # Play the subtle beep when this profile's hotkey fires. On by default.
    hotkey_beep: bool = True
    # "vad" = auto-stop on trailing silence; "toggle" = press to start, press
    # the same key again to stop (push-to-talk style).
    capture_mode: str = "vad"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Profile:
        return cls(
            id=str(d.get("id", "")),
            name=str(d.get("name", "")),
            hotkey=str(d.get("hotkey", "")),
            dest_root=str(d.get("dest_root", "")),
            path_template=str(d.get("path_template", "")),
            line_format=LineFormat.from_dict(d.get("line_format")),
            use_session_headers=bool(d.get("use_session_headers", True)),
            clip_from_file=bool(d.get("clip_from_file", False)),
            clip_file=str(d.get("clip_file", "")),
            context_from_obs=bool(d.get("context_from_obs", False)),
            hotkey_beep=bool(d.get("hotkey_beep", True)),
            capture_mode="toggle" if str(d.get("capture_mode", "vad")) == "toggle" else "vad",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "hotkey": self.hotkey,
            "dest_root": self.dest_root,
            "path_template": self.path_template,
            "line_format": self.line_format.to_dict(),
            "use_session_headers": self.use_session_headers,
            "clip_from_file": self.clip_from_file,
            "clip_file": self.clip_file,
            "context_from_obs": self.context_from_obs,
            "hotkey_beep": self.hotkey_beep,
            "capture_mode": self.capture_mode,
        }

    # --- resolution -------------------------------------------------------

    def resolve_path(
        self,
        context: str,
        now: datetime | None = None,
        placeholder: str = DEFAULT_PLACEHOLDER,
    ) -> Path:
        """Render ``path_template`` with the token values and join under
        ``dest_root``. Each token value is sanitized to a safe Windows component;
        the template's own separators (``\\`` or ``/``) are preserved."""
        now = now or datetime.now()
        ctx = sanitize_part(context) or placeholder
        tokens = {
            "profile": sanitize_part(self.id),
            "context": ctx,
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H-%M-%S"),
        }
        rendered = self.path_template
        for key, value in tokens.items():
            rendered = rendered.replace("{" + key + "}", value)
        return Path(self.dest_root) / rendered

    def render_line(self, text: str, now: datetime | None = None, clip: str | None = None) -> str:
        """Render the appended line. A ``{clip}`` token in the prefix is replaced
        with the recording-segment offset (see :meth:`clip_offset`); when that is
        empty the token and any now-empty ``[]``/``()`` wrapper around it are
        removed so the line stays clean. Pass ``clip`` to skip the file read."""
        now = now or datetime.now()
        prefix = self.line_format.prefix
        if "{clip}" in prefix:
            if clip is None:
                clip = self.clip_offset(now)
            prefix = prefix.replace("{clip}", clip or "")
            if not clip:
                prefix = re.sub(r"\[\s*\]|\(\s*\)", "", prefix)
                prefix = re.sub(r"\s{2,}", " ", prefix).lstrip()
        ts = now.strftime(self.line_format.timestamp_format)
        return f"- [{ts}] {prefix}{text}\n"

    def sidecar_snapshot(self) -> SidecarSnapshot | None:
        """One read of this profile's OBS sidecar, or None when the profile does
        not read OBS info. Take this once per note and pass it to the methods
        below so the session header, {clip}, file sub-header, and game all
        describe the same moment (and the file is read once, not four times)."""
        if self.clip_from_file and self.clip_file:
            return read_sidecar(self.clip_file)
        return None

    def session_header_value(
        self, now: datetime | None = None, sidecar: SidecarSnapshot | None = None
    ) -> str:
        """The value for the ``## Recording session:`` header: the recording's
        start time (sidecar ``session_start``) while a recording is active and
        the profile reads OBS info via the clip option, else the date. Guards
        mirror :meth:`clip_offset`, so all OBS-derived note decoration goes
        quiet together when recording stops. ``sidecar`` (from
        :meth:`sidecar_snapshot`) skips the file read."""
        now = now or datetime.now()
        if self.clip_from_file and self.clip_file:
            data = (sidecar if sidecar is not None else read_sidecar(self.clip_file)).data
            if data and data.get("recording") is not False:
                val = str(data.get("session_start", "") or "").strip()
                if val:
                    return val
        return now.strftime("%Y-%m-%d")

    def clip_offset(
        self, now: datetime | None = None, sidecar: SidecarSnapshot | None = None
    ) -> str:
        """Elapsed position into the current OBS recording segment, formatted (see
        :func:`format_offset`), or ``""`` when: the option is off, the sidecar is
        missing/unreadable, recording is not active, ``file_start`` is absent or
        unparseable, or the offset would be negative (a stale sidecar)."""
        if not (self.clip_from_file and self.clip_file):
            return ""
        data = (sidecar if sidecar is not None else read_sidecar(self.clip_file)).data
        if not data or data.get("recording") is False:
            return ""
        start = _parse_sidecar_time(str(data.get("file_start", "")))
        if start is None:
            return ""
        now = now or datetime.now()
        seconds = (now - start).total_seconds()
        if seconds < 0:
            return ""
        return format_offset(seconds)

    def recording_file_name(self, sidecar: SidecarSnapshot | None = None) -> str:
        """Base name of the current OBS recording file (sidecar ``file_path``),
        for the ``### Recording file:`` sub-header, or ``""`` when: the clip
        option is off, the sidecar is missing/unreadable, recording is not
        active, or the sidecar has no file path. Guards mirror
        :meth:`clip_offset` so a note with no {clip} stamp never introduces a
        file sub-header."""
        if not (self.clip_from_file and self.clip_file):
            return ""
        data = (sidecar if sidecar is not None else read_sidecar(self.clip_file)).data
        if not data or data.get("recording") is False:
            return ""
        file_path = str(data.get("file_path", "") or "").strip()
        if not file_path:
            return ""
        # PureWindowsPath handles OBS paths with either separator on any host OS.
        return PureWindowsPath(file_path).name.strip()

    def effective_context(
        self, global_context_cfg: dict[str, Any], sidecar: SidecarSnapshot | None = None
    ) -> str:
        """The {context} value for this profile: the global context, unless the
        profile reads OBS info and opts into sourcing the context (the game)
        from that same file. The override fully replaces the global context --
        an absent sidecar or empty game yields "", like the global file source.
        Unlike the other OBS-derived decorations it does not go quiet when
        recording stops: the last game is still the best guess at what is
        being played."""
        if self.clip_from_file and self.clip_file and self.context_from_obs:
            snap = sidecar if sidecar is not None else read_sidecar(self.clip_file)
            return snap.context_value()
        return read_context(global_context_cfg)


def profiles_from_config(cfg: dict[str, Any]) -> list[Profile]:
    return [Profile.from_dict(d) for d in cfg.get("profiles", [])]


def validate_profiles(profiles: list[Profile]) -> list[str]:
    """Return a list of human-readable problems. Empty list means valid.

    Checks: non-empty id/name/dest_root/hotkey, unique ids, unique hotkeys."""
    errors: list[str] = []
    seen_ids: dict[str, int] = {}
    seen_hotkeys: dict[str, str] = {}

    for i, p in enumerate(profiles):
        label = p.name or p.id or f"profile #{i + 1}"
        if not p.id:
            errors.append(f"{label}: missing id")
        if not p.name:
            errors.append(f"{label}: missing name")
        if not p.dest_root:
            errors.append(f"{label}: missing destination root")
        if not p.hotkey:
            errors.append(f"{label}: missing hotkey")

        if p.id:
            if p.id in seen_ids:
                errors.append(f"duplicate id '{p.id}'")
            seen_ids[p.id] = i
        if p.hotkey:
            if p.hotkey in seen_hotkeys:
                errors.append(
                    f"hotkey '{p.hotkey}' is used by both '{seen_hotkeys[p.hotkey]}' and '{label}'"
                )
            seen_hotkeys[p.hotkey] = label

        # The template must stay relative to dest_root: an absolute or '..' path
        # would escape it (Path(dest_root) / "C:\\x" yields "C:\\x").
        if p.path_template:
            tmpl = PureWindowsPath(p.path_template.replace("/", "\\"))
            if tmpl.is_absolute() or tmpl.drive or p.path_template.startswith(("\\", "/")):
                errors.append(
                    f"{label}: path template must be relative (no drive or leading slash)"
                )
            if ".." in tmpl.parts:
                errors.append(f"{label}: path template must not contain '..'")

    return errors


def read_context(context_cfg: dict[str, Any]) -> str:
    """The app-owned context value. ``source: "manual"`` returns the stored
    value; ``source: "file"`` re-reads ``file_path`` each call (the optional OBS
    bridge; a JSON sidecar's ``game`` key or a plain-text value both work).
    Missing/unreadable yields ""."""
    source = context_cfg.get("source", "manual")
    if source == "file":
        file_path = context_cfg.get("file_path", "")
        if not file_path:
            return ""
        return read_sidecar(file_path).context_value()
    return str(context_cfg.get("value", "") or "").strip()
