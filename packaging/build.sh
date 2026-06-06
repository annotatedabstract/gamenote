#!/usr/bin/env bash
# Build gamenote into a one-folder Windows app with PyInstaller.
# Git Bash friendly. Run from anywhere; it cd's to the repo root.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"

MODEL_DIR="packaging/model_cache/small.en"

# 1. Fetch the model to bundle (one time; ~480 MB). Skipped if already present.
if [ ! -f "$MODEL_DIR/model.bin" ]; then
  echo "Downloading small.en model for bundling..."
  python -c "from pathlib import Path; from faster_whisper.utils import download_model; Path('$MODEL_DIR').mkdir(parents=True, exist_ok=True); download_model('small.en', output_dir='$MODEL_DIR')"
fi

# 2. Ensure PyInstaller is available.
if ! python -c "import PyInstaller" 2>/dev/null; then
  echo "Installing PyInstaller..."
  python -m pip install pyinstaller
fi

# 3. Build (one-folder). --clean wipes caches so spec edits take effect.
echo "Building with PyInstaller..."
python -m PyInstaller --noconfirm --clean packaging/gamenote.spec

echo
echo "Done. Distribute the whole folder:  dist/gamenote/"
echo "Run it with:                        dist/gamenote/gamenote.exe"
