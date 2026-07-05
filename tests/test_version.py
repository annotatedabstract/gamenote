"""Version single-sourcing guards.

The version lives only in ``gamenote/__init__.py``; the installer and both CI
workflows receive it via ``/DMyAppVersion``. These tests keep that true: the
.iss must never grow a real hardcoded version again, the CHANGELOG must have a
section for the current version (so a bump is always documented), and the
release-notes extractor must find it.
"""

import importlib.util
import re
from pathlib import Path

import gamenote

_ROOT = Path(__file__).resolve().parents[1]


def _load_release_notes_module():
    spec = importlib.util.spec_from_file_location(
        "release_notes", _ROOT / "packaging" / "release_notes.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_version_is_well_formed():
    assert re.fullmatch(r"\d+\.\d+\.\d+", gamenote.__version__)


def test_installer_iss_has_no_hardcoded_version():
    """installer.iss may only define the '0.0.0-unset' sentinel (guarded by
    #ifndef); a real version there would silently drift from __init__.py."""
    iss = (_ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    defines = re.findall(r'#define\s+MyAppVersion\s+"([^"]+)"', iss)
    assert defines == ["0.0.0-unset"]
    assert "#ifndef MyAppVersion" in iss


def test_changelog_has_a_section_for_the_current_version():
    """A version bump must come with CHANGELOG notes: the release workflow
    publishes the matching section as the release notes."""
    changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## \[{re.escape(gamenote.__version__)}\]", changelog, re.MULTILINE), (
        f"CHANGELOG.md has no '## [{gamenote.__version__}]' section"
    )


def test_release_notes_extracts_the_current_version_section():
    rn = _load_release_notes_module()
    changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = rn.extract_section(changelog, gamenote.__version__)
    assert section  # non-empty body
    assert "## [" not in section  # stops before the next version section
    assert not re.search(r"^\[[^\]]+\]:", section, re.MULTILINE)  # no link defs


def test_release_notes_section_boundaries():
    rn = _load_release_notes_module()
    changelog = (
        "# Changelog\n\n"
        "## [Unreleased]\n\n- pending\n\n"
        "## [2.0.0] - 2026-01-02\n\n### Added\n- brand new\n\n"
        "## [1.9.0] - 2026-01-01\n\n### Fixed\n- old fix\n\n"
        "[Unreleased]: https://example.test/compare/v2.0.0...HEAD\n"
        "[2.0.0]: https://example.test/compare/v1.9.0...v2.0.0\n"
    )
    assert rn.extract_section(changelog, "2.0.0") == "### Added\n- brand new"
    assert rn.extract_section(changelog, "1.9.0") == "### Fixed\n- old fix"
    assert rn.extract_section(changelog, "3.0.0") is None
