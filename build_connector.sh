#!/usr/bin/env bash
# =============================================================================
# CryoStack Connector — build one platform artifact on the current host.
#
# This is a single-host PyInstaller build. It produces the artifact for the
# machine it runs on:
#
#     linux-x86_64   ->  CryoStack-Connector-linux-x86_64.tar.gz
#     macos-arm64    ->  CryoStack-Connector-macos-arm64.dmg
#     macos-x86_64   ->  CryoStack-Connector-macos-x86_64.dmg
#     windows-x86_64 ->  CryoStack-Connector-windows-x86_64.exe
#
# It cannot cross-build. To publish every platform, run this script once on a
# Linux host, once on a Mac, and once on Windows, then collect the artifacts
# into dist/packages/ before running build_deploy_connector.sh.
# =============================================================================
set -euo pipefail

# ---- configuration ---------------------------------------------------------
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

APP_BRAND="CryoStack Connector"          # human-readable application name
APP_BASENAME="CryoStack-Connector"       # PyInstaller --name / artifact stem
SRC_ENTRY="icesee_hpc_connector/connector_menubar_app.py"

BUILD_DIR="$REPO_ROOT/build/connector"   # PyInstaller work + spec
DIST_DIR="$REPO_ROOT/dist/connector"     # PyInstaller output (binary / .app)
PKG_DIR="$REPO_ROOT/dist/packages"       # final distributable artifacts

# ---- host platform -------------------------------------------------------
OS="${CRYOSTACK_BUILD_OS:-$(uname -s)}"
ARCH="${CRYOSTACK_BUILD_ARCH:-$(uname -m)}"

case "$OS" in
  Darwin)               OS_TAG="macos" ;;
  Linux)                OS_TAG="linux" ;;
  MINGW*|MSYS*|CYGWIN*|Windows_NT) OS_TAG="windows" ;;
  *) echo "ERROR: unsupported build OS: $OS" >&2; exit 2 ;;
esac

case "$ARCH" in
  x86_64|amd64|AMD64)   ARCH_TAG="x86_64" ;;
  arm64|aarch64)        ARCH_TAG="arm64" ;;
  *) echo "ERROR: unsupported build architecture: $ARCH" >&2; exit 2 ;;
esac

PLATFORM="${OS_TAG}-${ARCH_TAG}"

case "$PLATFORM" in
  linux-*)   ARTIFACT="${APP_BASENAME}-${PLATFORM}.tar.gz" ;;
  macos-*)   ARTIFACT="${APP_BASENAME}-${PLATFORM}.dmg" ;;
  windows-*) ARTIFACT="${APP_BASENAME}-${PLATFORM}.exe" ;;
  *) echo "ERROR: no packaging rule for platform: $PLATFORM" >&2; exit 2 ;;
esac
ARTIFACT_PATH="$PKG_DIR/$ARTIFACT"

echo "=============================================================="
echo " CryoStack Connector build"
echo "   host platform : $PLATFORM"
echo "   entrypoint    : $SRC_ENTRY"
echo "   artifact      : dist/packages/$ARTIFACT"
echo "=============================================================="

# ---- dependencies -------------------------------------------------------
python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet pyinstaller websockets requests paramiko

# ---- clean --------------------------------------------------------------
rm -rf "$BUILD_DIR" "$DIST_DIR"
mkdir -p "$BUILD_DIR" "$DIST_DIR" "$PKG_DIR"
rm -f "$ARTIFACT_PATH"

PYI_ARGS=(
  --name "$APP_BASENAME"
  --onefile
  --windowed
  --clean
  --noconfirm
  --paths "$REPO_ROOT"
  --workpath "$BUILD_DIR"
  --specpath "$BUILD_DIR"
  --distpath "$DIST_DIR"
  --collect-submodules icesee_hpc_connector
  --collect-all paramiko
  --hidden-import paramiko
)

# ---- build per platform ----------------------------------------------
if [[ "$OS_TAG" == "macos" ]]; then
  python3 -m pip install --quiet rumps
  PYTHONPATH="$REPO_ROOT" pyinstaller "${PYI_ARGS[@]}" \
    --hidden-import rumps --hidden-import Foundation --hidden-import AppKit \
    "$SRC_ENTRY"

  APP_BUNDLE="$DIST_DIR/${APP_BASENAME}.app"
  [[ -d "$APP_BUNDLE" ]] || { echo "ERROR: PyInstaller did not produce $APP_BUNDLE" >&2; exit 1; }

  hdiutil create \
    -volname "$APP_BRAND" \
    -srcfolder "$APP_BUNDLE" \
    -ov -format UDZO \
    "$ARTIFACT_PATH"

elif [[ "$OS_TAG" == "linux" ]]; then
  python3 -m pip install --quiet pystray pillow
  PYTHONPATH="$REPO_ROOT" pyinstaller "${PYI_ARGS[@]}" \
    --hidden-import pystray --hidden-import PIL \
    --hidden-import tkinter --hidden-import tkinter.simpledialog \
    "$SRC_ENTRY"

  BIN="$DIST_DIR/${APP_BASENAME}"
  [[ -f "$BIN" ]] || { echo "ERROR: PyInstaller did not produce $BIN" >&2; exit 1; }
  chmod +x "$BIN"
  tar -czf "$ARTIFACT_PATH" -C "$DIST_DIR" "${APP_BASENAME}"

else  # windows
  python3 -m pip install --quiet pystray pillow
  PYTHONPATH="$REPO_ROOT" pyinstaller "${PYI_ARGS[@]}" \
    --hidden-import pystray --hidden-import PIL \
    --hidden-import tkinter --hidden-import tkinter.simpledialog \
    "$SRC_ENTRY"

  EXE="$DIST_DIR/${APP_BASENAME}.exe"
  [[ -f "$EXE" ]] || { echo "ERROR: PyInstaller did not produce $EXE" >&2; exit 1; }
  cp "$EXE" "$ARTIFACT_PATH"
fi

# ---- verify -----------------------------------------------------------
if [[ ! -s "$ARTIFACT_PATH" ]]; then
  echo "ERROR: build reported success but the artifact is missing or empty:" >&2
  echo "       $ARTIFACT_PATH" >&2
  exit 1
fi

# ---- build-metadata sidecar (authoritative build time, survives host copy) --
if command -v sha256sum >/dev/null 2>&1; then
  SHA="$(cd "$PKG_DIR" && sha256sum "$ARTIFACT" | awk '{print $1}')"
else
  SHA="$(cd "$PKG_DIR" && shasum -a 256 "$ARTIFACT" | awk '{print $1}')"
fi
SIZE_BYTES="$(wc -c < "$ARTIFACT_PATH" | tr -d ' ')"
BUILT_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cat > "${ARTIFACT_PATH}.build.json" <<JSON
{
  "platform": "${PLATFORM}",
  "filename": "${ARTIFACT}",
  "sha256": "${SHA}",
  "size_bytes": ${SIZE_BYTES},
  "built_at": "${BUILT_AT}"
}
JSON

# ---- manifest.json + SHA256SUMS -----------------------------------------
# Deployment regenerates these from the full published set; here we keep them
# consistent with whatever this host has built so far.
python3 "$REPO_ROOT/deployment/connector_manifest.py" generate "$PKG_DIR"

# ---- summary --------------------------------------------------------
HUMAN_SIZE="$(du -h "$ARTIFACT_PATH" | awk '{print $1}')"
echo
echo "=============================================================="
echo " Built for this host:"
echo "   $ARTIFACT   (${HUMAN_SIZE}, ${SIZE_BYTES} bytes)"
echo "   sha256: $SHA"
echo
echo " NOT built on this host (single-host build cannot cross-compile):"
for p in linux-x86_64 macos-arm64 macos-x86_64 windows-x86_64; do
  [[ "$p" == "$PLATFORM" ]] && continue
  echo "   - $p  (run build_connector.sh on that platform)"
done
echo
echo " Artifacts collected in: dist/packages/"
ls -lh "$PKG_DIR"
echo "=============================================================="
