#!/usr/bin/env bash
set -euo pipefail

python3 -m pip install --upgrade pip pyinstaller websockets requests

OS="$(uname -s)"
ARCH="$(uname -m)"

rm -rf build dist *.spec

COMMON_ARGS=(
  --name "ICESEE_Connector_${OS}_${ARCH}"
  --onefile
  --windowed
  --clean
  --paths "$PWD"
  --collect-submodules icesee_hpc_connector
)

if [[ "$OS" == "Darwin" ]]; then
  python3 -m pip install rumps

  PYTHONPATH="$PWD" pyinstaller \
    "${COMMON_ARGS[@]}" \
    --hidden-import rumps \
    --hidden-import Foundation \
    --hidden-import AppKit \
    icesee_hpc_connector/connector_menubar_app.py

elif [[ "$OS" == "Linux" ]]; then
  python3 -m pip install pystray pillow

  PYTHONPATH="$PWD" pyinstaller \
    "${COMMON_ARGS[@]}" \
    --hidden-import pystray \
    --hidden-import PIL \
    icesee_hpc_connector/connector_menubar_app.py

else
  python3 -m pip install pystray pillow

  PYTHONPATH="$PWD" pyinstaller \
    "${COMMON_ARGS[@]}" \
    --hidden-import pystray \
    --hidden-import PIL \
    icesee_hpc_connector/connector_menubar_app.py
fi