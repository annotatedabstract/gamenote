"""Print the CHANGELOG.md section for one version, for GitHub release notes.

Used by the release workflow: ``python packaging/release_notes.py v1.5.0``
writes the matching ``## [1.5.0]`` section body to stdout. Falls back to a
pointer at the CHANGELOG when the section is missing, so a release never
fails just because the notes step could not find one.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def extract_section(changelog: str, version: str) -> str | None:
    """The body of the ``## [<version>]`` section (until the next ``## [`` or
    the link-definition block at the end), or None if there is no section."""
    pattern = re.compile(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]]+\]:|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(changelog)
    return m.group(1).strip() if m else None


def main(argv: list[str]) -> int:
    # The consumer (gh --notes-file) reads UTF-8; without this, a redirected
    # stdout on Windows writes the locale codepage (cp1252) and an en-dash in
    # the CHANGELOG becomes a replacement character in the release notes.
    sys.stdout.reconfigure(encoding="utf-8")
    if len(argv) != 2:
        print("usage: release_notes.py <version|vX.Y.Z>", file=sys.stderr)
        return 2
    version = argv[1].strip().lstrip("vV")
    path = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
    section = extract_section(path.read_text(encoding="utf-8"), version)
    if section is None:
        print(f"See CHANGELOG.md for the changes in {version}.")
        print(f"WARNING: no CHANGELOG section found for {version}.", file=sys.stderr)
        return 0
    print(section)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
