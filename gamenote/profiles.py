"""Profiles, the destination resolver, and the line-format renderer.

A profile decides where a note goes and how the appended line looks. The model
and all capture/VAD tuning stay global (see the handoff Section 3); a profile is
purely about destination and format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Characters Windows forbids in a path component, plus we trim trailing dots and
# spaces (also illegal at the end of a Windows name).
_INVALID_CHARS = '<>:"/\\|?*'

# Where a note lands when {context} is used but the context is empty.
DEFAULT_PLACEHOLDER = "_Unsorted"


def sanitize_part(value: str) -> str:
    """Make ``value`` safe as a single Windows path component. Strips forbidden
    characters and control characters, then trailing dots and spaces. Returns an
    empty string if nothing survives (the caller decides on a fallback)."""
    cleaned = "".join(c for c in value if c not in _INVALID_CHARS and ord(c) >= 32)
    return cleaned.strip().rstrip(" .")


@dataclass
class LineFormat:
    timestamp_format: str = "%Y-%m-%d %H:%M:%S"
    prefix: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "LineFormat":
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
    # Play the subtle beep when this profile's hotkey fires. On by default.
    hotkey_beep: bool = True
    # "vad" = auto-stop on trailing silence; "toggle" = press to start, press
    # the same key again to stop (push-to-talk style).
    capture_mode: str = "vad"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Profile":
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

    def render_line(self, text: str, now: datetime | None = None) -> str:
        now = now or datetime.now()
        ts = now.strftime(self.line_format.timestamp_format)
        return f"- [{ts}] {self.line_format.prefix}{text}\n"

    def session_header_value(self, now: datetime | None = None) -> str:
        """The value for the ``## Recording session:`` header. When the legacy
        file option is on, read it from the ``.current_session`` file (falling
        back to the date if the file is missing or empty). Otherwise the date."""
        now = now or datetime.now()
        if self.session_from_file and self.session_file:
            try:
                val = Path(self.session_file).read_text(encoding="utf-8").strip()
                if val:
                    return val
            except OSError:
                pass
        return now.strftime("%Y-%m-%d")


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
                    f"hotkey '{p.hotkey}' is used by both "
                    f"'{seen_hotkeys[p.hotkey]}' and '{label}'"
                )
            seen_hotkeys[p.hotkey] = label

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
        try:
            return Path(file_path).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return str(context_cfg.get("value", "") or "").strip()
