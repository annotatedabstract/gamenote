#!/usr/bin/env bash
# Build gamenote into a one-folder Windows app with PyInstaller.
# Git Bash friendly. Run from anywhere; it cd's to the repo root.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"

# The model is not bundled; it downloads on first run. So the build is just
# PyInstaller, which keeps the installer small.

# Ensure PyInstaller is available.
if ! python -c "import PyInstaller" 2>/dev/null; then
  echo "Installing PyInstaller..."
  python -m pip install pyinstaller
fi

# Stamp the build identity (bundled by the spec; read by the in-app dev update
# channel and by CI when composing the dev release body). Best-effort: a build
# without git still works, it just carries no identity.
if git rev-parse HEAD >/dev/null 2>&1; then
  printf '{"commit": "%s", "built_at": "%s", "version": "%s"}\n' \
    "$(git rev-parse HEAD)" \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$(python -c 'import gamenote; print(gamenote.__version__)')" \
    > build_info.json
  echo "Stamped build_info.json: $(git rev-parse --short HEAD)"
else
  echo "WARNING: git unavailable; build_info.json not stamped."
fi

# Build (one-folder). --clean wipes caches so spec edits take effect.
echo "Building with PyInstaller..."
python -m PyInstaller --noconfirm --clean packaging/gamenote.spec

echo
echo "Done. Distribute the whole folder:  dist/gamenote/"
echo "Run it with:                        dist/gamenote/gamenote.exe"
