import re
from pathlib import Path

import gamenote


def test_version_matches_installer_iss():
    """gamenote.__version__ must equal MyAppVersion in packaging/installer.iss.
    The two are hand-maintained; this guards against a mislabeled release if only
    one is bumped."""
    root = Path(__file__).resolve().parents[1]
    iss = (root / "packaging" / "installer.iss").read_text(encoding="utf-8")
    m = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', iss)
    assert m is not None, "MyAppVersion not found in installer.iss"
    assert m.group(1) == gamenote.__version__
