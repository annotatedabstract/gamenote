#!/usr/bin/env bash
# Build the gamenote Windows installer (setup.exe) with Inno Setup.
# Ensures the one-folder app exists first (runs build.sh if needed), then compiles
# packaging/installer.iss. Output lands in packaging/installer_output/.
#
# Requires Inno Setup 6 (ISCC.exe):  winget install JRSoftware.InnoSetup
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"

# 1. Ensure the PyInstaller one-folder build exists.
if [ ! -f "dist/gamenote/gamenote.exe" ]; then
  echo "dist/gamenote not found; building the app first..."
  bash packaging/build.sh
fi

# 2. Locate the Inno Setup compiler.
ISCC=""
for cand in \
  "$(command -v iscc 2>/dev/null || true)" \
  "/c/Program Files (x86)/Inno Setup 6/ISCC.exe" \
  "/c/Program Files/Inno Setup 6/ISCC.exe" \
  "$HOME/AppData/Local/Programs/Inno Setup 6/ISCC.exe" \
  "$LOCALAPPDATA/Programs/Inno Setup 6/ISCC.exe"; do
  if [ -n "$cand" ] && [ -f "$cand" ]; then ISCC="$cand"; break; fi
done

if [ -z "$ISCC" ]; then
  echo "ERROR: Inno Setup compiler (ISCC.exe) not found." >&2
  echo "Install it with:  winget install JRSoftware.InnoSetup" >&2
  exit 1
fi

# 3. Compile the installer, stamping the app version from the single source
#    of truth (gamenote/__init__.py). MSYS_NO_PATHCONV/MSYS2_ARG_CONV_EXCL stop
#    Git Bash from mangling the /D switch into a Windows path.
VERSION="$(python -c 'import gamenote; print(gamenote.__version__)')"
echo "Compiling installer for version $VERSION with: $ISCC"
MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="/D" \
  "$ISCC" "/DMyAppVersion=$VERSION" packaging/installer.iss

echo
echo "Done. Installer is in packaging/installer_output/"
