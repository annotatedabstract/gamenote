"""Note file writing: path resolution glue, the header tail-scan, and the
append itself, generalized to take a :class:`~gamenote.profiles.Profile`.

The header logic reads the last 8 KB of the file, finds the most recent
``## Recording session:`` header, and only writes a new header when the file is
new or the value changed. Without OBS there is no recording timestamp, so the
header value is the date. When the profile stamps recording positions from an
OBS sidecar, a ``### Recording file:`` sub-header likewise tracks the current
recording file, so {clip} offsets stay attributable across OBS file splits.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path

from .profiles import Profile, SidecarSnapshot

log = logging.getLogger("gamenote.notes")

SESSION_HEADER_RE = re.compile(r"^## Recording session:\s*(.+?)\s*$", re.MULTILINE)
FILE_HEADER_RE = re.compile(r"^### Recording file:\s*(.+?)\s*$", re.MULTILINE)

_TAIL_BYTES = 8192


def _tail_text(path: Path) -> str | None:
    """The last ~8 KB of the file decoded as UTF-8, or None if it is missing."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - _TAIL_BYTES))
            return f.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return None


def last_headers_in_file(path: Path) -> tuple[str | None, str | None]:
    """(most recent session-header value, most recent file-header value), each
    None when absent. The file-header scan only considers text after the last
    session header, so a ``### Recording file:`` line from a previous session
    never counts for the current one."""
    tail = _tail_text(path)
    if tail is None:
        return None, None
    session = None
    pos = 0
    for m in SESSION_HEADER_RE.finditer(tail):
        session = m.group(1)
        pos = m.end()
    # findall with pos: ^ still anchors against real newlines in `tail`, so
    # header lines after the session line all match.
    files = FILE_HEADER_RE.findall(tail, pos)
    return session, (files[-1] if files else None)


def _title(profile: Profile, context: str) -> str:
    """H1 for a brand-new file. With a context, preserve the old
    ``# <Game> notes`` look; otherwise title the file by the profile name (so a
    flat file reads ``# Bugs``, not ``# Bugs notes``)."""
    ctx = context.strip()
    return f"# {ctx} notes" if ctx else f"# {profile.name}"


def append_note(
    profile: Profile,
    context: str,
    text: str,
    now: datetime | None = None,
    sidecar: SidecarSnapshot | None = None,
) -> Path:
    """Append a formatted note line for ``profile`` and return the file path.

    Creates the destination directory, writes an H1 on a new file, manages the
    date-based session header (when the profile enables headers) and the
    recording-file sub-header (when the profile stamps recording positions),
    then appends the rendered line. Pass ``sidecar`` (one
    :meth:`~gamenote.profiles.Profile.sidecar_snapshot` per note) so the header,
    sub-header, and {clip} token all come from a single consistent read; without
    it each falls back to reading the file itself."""
    now = now or datetime.now()
    path = profile.resolve_path(context, now)
    path.parent.mkdir(parents=True, exist_ok=True)

    clip = profile.clip_offset(now, sidecar=sidecar) if sidecar is not None else None
    line = profile.render_line(text, now, clip=clip)
    new_file = not path.exists()

    need_header = False
    header_value = ""
    file_name = ""
    need_file_header = False
    if profile.use_session_headers:
        header_value = profile.session_header_value(now, sidecar=sidecar)
        last_session, last_file = (None, None) if new_file else last_headers_in_file(path)
        need_header = new_file or (last_session != header_value)
        file_name = profile.recording_file_name(sidecar=sidecar)
        need_file_header = bool(file_name) and (need_header or last_file != file_name)

    with open(path, "a", encoding="utf-8") as f:
        if new_file:
            f.write(_title(profile, context) + "\n")
        if need_header:
            f.write(f"\n## Recording session: {header_value}\n\n")
        if need_file_header:
            # The session-header block already ends in a blank line; otherwise
            # separate the sub-header from the previous note.
            sep = "" if need_header else "\n"
            f.write(f"{sep}### Recording file: {file_name}\n\n")
        f.write(line)

    log.info("Saved note to %s", path)
    return path
