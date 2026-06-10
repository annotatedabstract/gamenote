"""Profiles, the destination resolver, and the line-format renderer.

A profile decides where a note goes and how the appended line looks. The model
and all capture/VAD tuning stay global; a profile is purely about destination
and format.
"""

from __future__ import annotations

import json
import re
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


def _read_sidecar(path: str) -> dict[str, Any] | None:
    """Parse a ``gamenote-obs.json`` sidecar into a dict, or None if the file is
    missing, unreadable, empty, or not a JSON object (e.g. a legacy plain-text
    ``.current_session`` / ``.current_game`` value). Callers fall back accordingly."""
    if not path:
        return None
    try:
        raw = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:  # includes json.JSONDecodeError; plain-text value
        return None
    return data if isinstance(data, dict) else None


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
    # Legacy option: source the session-header value from a .current_session file
    # (written by OBS) instead of the date. Off by default.
    session_from_file: bool = False
    session_file: str = ""
    # Optional: stamp the note with its position into the current OBS recording
    # segment, read from a gamenote-obs.json sidecar (see integrations/obs). The
    # value fills the {clip} token in the line prefix; omitted when unavailable.
    clip_from_file: bool = False
    clip_file: str = ""
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
            session_from_file=bool(d.get("session_from_file", False)),
            session_file=str(d.get("session_file", "")),
            clip_from_file=bool(d.get("clip_from_file", False)),
            clip_file=str(d.get("clip_file", "")),
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
            "session_from_file": self.session_from_file,
            "session_file": self.session_file,
            "clip_from_file": self.clip_from_file,
            "clip_file": self.clip_file,
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

    def session_header_value(self, now: datetime | None = None) -> str:
        """The value for the ``## Recording session:`` header. When the legacy
        file option is on, read it from the ``.current_session`` file (falling
        back to the date if the file is missing or empty). Otherwise the date."""
        now = now or datetime.now()
        if self.session_from_file and self.session_file:
            data = _read_sidecar(self.session_file)
            if data is not None:
                val = str(data.get("session_start", "") or "").strip()
                if val:
                    return val
            else:
                try:
                    val = Path(self.session_file).read_text(encoding="utf-8").strip()
                    if val:
                        return val
                except OSError:
                    pass
        return now.strftime("%Y-%m-%d")

    def clip_offset(self, now: datetime | None = None) -> str:
        """Elapsed position into the current OBS recording segment, formatted (see
        :func:`format_offset`), or ``""`` when: the option is off, the sidecar is
        missing/unreadable, recording is not active, ``file_start`` is absent or
        unparseable, or the offset would be negative (a stale sidecar)."""
        if not (self.clip_from_file and self.clip_file):
            return ""
        data = _read_sidecar(self.clip_file)
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

    def recording_file_name(self) -> str:
        """Base name of the current OBS recording file (sidecar ``file_path``),
        for the ``### Recording file:`` sub-header, or ``""`` when: the clip
        option is off, the sidecar is missing/unreadable, recording is not
        active, or the sidecar has no file path. Guards mirror
        :meth:`clip_offset` so a note with no {clip} stamp never introduces a
        file sub-header."""
        if not (self.clip_from_file and self.clip_file):
            return ""
        data = _read_sidecar(self.clip_file)
        if not data or data.get("recording") is False:
            return ""
        file_path = str(data.get("file_path", "") or "").strip()
        if not file_path:
            return ""
        # PureWindowsPath handles OBS paths with either separator on any host OS.
        return PureWindowsPath(file_path).name.strip()


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
    bridge, e.g. pointing at ``.current_game``). Missing/unreadable yields ""."""
    source = context_cfg.get("source", "manual")
    if source == "file":
        file_path = context_cfg.get("file_path", "")
        if not file_path:
            return ""
        data = _read_sidecar(file_path)
        if data is not None:
            return str(data.get("game", "") or "").strip()
        try:
            return Path(file_path).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return str(context_cfg.get("value", "") or "").strip()
