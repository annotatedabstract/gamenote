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

# Build (one-folder). --clean wipes caches so spec edits take effect.
echo "Building with PyInstaller..."
python -m PyInstaller --noconfirm --clean packaging/gamenote.spec

echo
echo "Done. Distribute the whole folder:  dist/gamenote/"
echo "Run it with:                        dist/gamenote/gamenote.exe"
