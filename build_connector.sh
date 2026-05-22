#!/usr/bin/env bash
set -euo pipefail

python3 -m pip install --upgrade pip
python3 -m pip install pyinstaller websockets requests paramiko

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Darwin) OS_TAG="macOS" ;;
  Linux)  OS_TAG="Linux" ;;
  MINGW*|MSYS*|CYGWIN*) OS_TAG="Windows" ;;
  *) OS_TAG="$OS" ;;
esac

case "$ARCH" in
  x86_64|amd64) ARCH_TAG="x86_64" ;;
  arm64|aarch64) ARCH_TAG="arm64" ;;
  *) ARCH_TAG="$ARCH" ;;
esac

APP_BASENAME="Cryolauncher_Connector"
DIST_NAME="${APP_BASENAME}_${OS_TAG}_${ARCH_TAG}"

rm -rf build dist *.spec
mkdir -p dist/packages

COMMON_ARGS=(
  --name "$APP_BASENAME"
  --onedir
  --windowed
  --clean
  --paths "$PWD"
  --collect-submodules icesee_hpc_connector
  --collect-all paramiko
  --hidden-import paramiko
)

if [[ "$OS" == "Darwin" ]]; then
  python3 -m pip install rumps

  PYTHONPATH="$PWD" pyinstaller \
    "${COMMON_ARGS[@]}" \
    --hidden-import rumps \
    --hidden-import Foundation \
    --hidden-import AppKit \
    icesee_hpc_connector/connector_menubar_app.py

  hdiutil create \
    -volname "ICESEE Connector" \
    -srcfolder "dist/${APP_BASENAME}.app" \
    -ov \
    -format UDZO \
    "dist/packages/${DIST_NAME}.dmg"

elif [[ "$OS" == "Linux" ]]; then
  python3 -m pip install pystray pillow

  PYTHONPATH="$PWD" pyinstaller \
    "${COMMON_ARGS[@]}" \
    --hidden-import pystray \
    --hidden-import PIL \
    icesee_hpc_connector/connector_menubar_app.py

  tar -czf "dist/packages/${DIST_NAME}.tar.gz" \
    -C dist "$APP_BASENAME"

else
  python3 -m pip install pystray pillow

  PYTHONPATH="$PWD" pyinstaller \
    "${COMMON_ARGS[@]}" \
    --hidden-import pystray \
    --hidden-import PIL \
    icesee_hpc_connector/connector_menubar_app.py

  cp "dist/${APP_BASENAME}.exe" \
     "dist/packages/${DIST_NAME}.exe"
fi

echo
echo "Built package(s):"
ls -lh dist/packages