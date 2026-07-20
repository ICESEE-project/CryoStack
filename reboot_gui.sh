#!/usr/bin/env bash

# ============================================================
# CryoStack GUI + Connector Launcher
# ============================================================

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}"

BOOK_DIR="${REPO_ROOT}/icesee_jupyter_book"
LIVIST_ROOT="${REPO_ROOT}/external/living-ice-sheet-temperature"
LIVIST_FRONTEND="${LIVIST_ROOT}/frontend"

GUI_LOG="${REPO_ROOT}/icesee.log"
RELAY_LOG="${REPO_ROOT}/relay.log"

cd "${REPO_ROOT}"

echo "=================================================="
echo "CryoStack service restart"
echo "Repository: ${REPO_ROOT}"
echo "=================================================="

echo
echo "=================================================="
echo "Stopping existing CryoStack services..."
echo "=================================================="

pkill -f "connector_relay_server" || true
pkill -f "icesee_app.py" || true
pkill -f "python.*-m voila" || true
pkill -f "python.*-m uvicorn" || true

sleep 2

echo
echo "=================================================="
echo "Building CryoStack..."
echo "=================================================="

# Remove the existing Jupyter Book build directory to ensure a clean build.
if [ -d "${BOOK_DIR}/_build" ]; then
    rm -rf "${BOOK_DIR}/_build"
fi

if ! command -v jupyter-book >/dev/null 2>&1; then
    echo "[CryoStack][ERROR] jupyter-book was not found in PATH."
    exit 1
fi

jupyter-book build "${BOOK_DIR}"

if [ ! -f "${BOOK_DIR}/_build/html/index.html" ]; then
    echo "[CryoStack][ERROR] Jupyter Book build did not produce index.html."
    exit 1
fi

echo
echo "=================================================="
echo "Building application documentation..."
echo "=================================================="

"${REPO_ROOT}/bin/build_application_docs.sh"

echo
echo "=================================================="
echo "Building LIVIST frontend..."
echo "=================================================="

if [ ! -d "${LIVIST_FRONTEND}" ]; then
    echo "[CryoStack][ERROR] LIVIST frontend directory was not found:"
    echo "  ${LIVIST_FRONTEND}"
    exit 1
fi

if ! command -v yarn >/dev/null 2>&1; then
    echo "[CryoStack][ERROR] yarn was not found in PATH."
    echo "Activate the Conda environment containing Node.js and Yarn."
    exit 1
fi

cd "${LIVIST_FRONTEND}"

# Keep dependencies synchronized with yarn.lock.
yarn install --immutable
yarn build

if [ ! -f "${LIVIST_FRONTEND}/dist/index.html" ]; then
    echo "[CryoStack][ERROR] LIVIST frontend build failed."
    exit 1
fi

echo
echo "=================================================="
echo "Building LIVIST documentation..."
echo "=================================================="

if ! command -v uv >/dev/null 2>&1; then
    echo "[CryoStack][ERROR] uv was not found in PATH."
    exit 1
fi

cd "${LIVIST_ROOT}"
uv run zensical build

if [ ! -f "${LIVIST_ROOT}/site/index.html" ]; then
    echo "[CryoStack][ERROR] LIVIST documentation build failed."
    exit 1
fi

cd "${REPO_ROOT}"

echo
echo "=================================================="
echo "Starting CryoStack GUI services..."
echo "=================================================="

nohup bash "${REPO_ROOT}/bin/start_icesee_services.sh" \
    > "${GUI_LOG}" 2>&1 &

GUI_PID=$!

sleep 5

if ! kill -0 "${GUI_PID}" 2>/dev/null; then
    echo "[CryoStack][ERROR] GUI service failed to start."
    echo "Inspect: ${GUI_LOG}"
    tail -n 50 "${GUI_LOG}" || true
    exit 1
fi

echo
echo "=================================================="
echo "Starting connector relay server..."
echo "=================================================="

nohup python -m uvicorn \
    icesee_jupyter_book.core.connector_relay_server:app \
    --host 127.0.0.1 \
    --port 8899 \
    > "${RELAY_LOG}" 2>&1 &

RELAY_PID=$!

sleep 3

if ! kill -0 "${RELAY_PID}" 2>/dev/null; then
    echo "[CryoStack][ERROR] Connector relay failed to start."
    echo "Inspect: ${RELAY_LOG}"
    tail -n 50 "${RELAY_LOG}" || true
    exit 1
fi

echo
echo "=================================================="
echo "CryoStack services started"
echo "=================================================="

printf "%-18s %s\n" "GUI PID:" "${GUI_PID}"
printf "%-18s %s\n" "Relay PID:" "${RELAY_PID}"

echo
echo "Applications:"
echo "  CryoStack:      http://127.0.0.1:8080/"
echo "  CryoLauncher:   http://127.0.0.1:8080/icesheets/"
echo "  ICESEE:         http://127.0.0.1:8080/icesee-gui/"
echo "  LIVIST:         http://127.0.0.1:8080/livist/"
echo "  LIVIST docs:    http://127.0.0.1:8080/livist/docs/"

echo
echo "Logs:"
echo "  tail -f ${GUI_LOG}"
echo "  tail -f ${RELAY_LOG}"

echo
echo "Ports:"
echo "  GUI:            8080"
echo "  Connector:      8899"

echo
echo "Running processes:"
ps -ef \
    | grep -E "icesee_app.py|voila|connector_relay_server|uvicorn" \
    | grep -v grep \
    || true