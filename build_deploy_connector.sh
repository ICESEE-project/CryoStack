#!/usr/bin/env bash
set -euo pipefail

APP_BASENAME="Cryolauncher_Connector"

REMOTE_USER="ubuntu"
REMOTE_HOST="3.23.36.158"
REMOTE_WEB_DIR="/var/www/html"
REMOTE_DOWNLOADS_DIR="${REMOTE_WEB_DIR}/downloads"

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

DIST_NAME="${APP_BASENAME}_${OS_TAG}_${ARCH_TAG}"

echo "Building ${DIST_NAME}..."
bash build_connector.sh

if [[ "$OS_TAG" == "Linux" ]]; then
  PACKAGE="dist/packages/${DIST_NAME}.tar.gz"
elif [[ "$OS_TAG" == "macOS" ]]; then
  PACKAGE="dist/packages/${DIST_NAME}.dmg"
elif [[ "$OS_TAG" == "Windows" ]]; then
  PACKAGE="dist/packages/${DIST_NAME}.exe"
else
  echo "Unsupported OS: $OS_TAG"
  exit 1
fi

if [[ ! -f "$PACKAGE" ]]; then
  echo "Package not found: $PACKAGE"
  echo "Available packages:"
  ls -lh dist/packages || true
  exit 1
fi

echo "Package ready: $PACKAGE"

echo "Creating remote downloads directory..."
ssh "${REMOTE_USER}@${REMOTE_HOST}" \
  "sudo mkdir -p ${REMOTE_DOWNLOADS_DIR} && sudo chown -R ${REMOTE_USER}:${REMOTE_USER} ${REMOTE_DOWNLOADS_DIR}"

echo "Uploading package..."
rsync -avz "$PACKAGE" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DOWNLOADS_DIR}/"

if [[ -f "index.html" ]]; then
  echo "Uploading index.html..."
  rsync -avz "index.html" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_WEB_DIR}/index.html"
fi

echo "Reloading nginx..."
ssh "${REMOTE_USER}@${REMOTE_HOST}" "sudo nginx -t && sudo systemctl reload nginx"

echo "Done."
echo "Uploaded: $(basename "$PACKAGE")"