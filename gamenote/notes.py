"""Note file writing: path resolution glue, the session-header tail-scan, and
the append itself, generalized to take a :class:`~gamenote.profiles.Profile`.

The session-header logic reads the last 8 KB of the file, finds the most recent
``## Recording session:`` header, and only writes a new header when the file is
new or the value changed. Without OBS there is no recording timestamp, so the
header value is the date.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path

from .profiles import Profile

log = logging.getLogger("gamenote.notes")

SESSION_HEADER_RE = re.compile(r"^## Recording session:\s*(.+?)\s*$", re.MULTILINE)


def last_session_in_file(path: Path) -> str | None:
    """Return the most recent session-header value in the file, or None."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 8192))
            tail = f.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return None
    matches = SESSION_HEADER_RE.findall(tail)
    return matches[-1] if matches else None


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
) -> Path:
    """Append a formatted note line for ``profile`` and return the file path.

    Creates the destination directory, writes an H1 on a new file, manages the
    date-based session header (when the profile enables headers), then appends
    the rendered line."""
    now = now or datetime.now()
    path = profile.resolve_path(context, now)
    path.parent.mkdir(parents=True, exist_ok=True)

    line = profile.render_line(text, now)
    new_file = not path.exists()

    need_header = False
    header_value = ""
    if profile.use_session_headers:
        header_value = profile.session_header_value(now)
        need_header = new_file or (last_session_in_file(path) != header_value)

    with open(path, "a", encoding="utf-8") as f:
        if new_file:
            f.write(_title(profile, context) + "\n")
        if need_header:
            f.write(f"\n## Recording session: {header_value}\n\n")
        f.write(line)

    log.info("Saved note to %s", path)
    return path
