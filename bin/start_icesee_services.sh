#!/bin/bash
set -euo pipefail

scriptDir="$(cd "$(dirname "$0")" && pwd)"
repoRoot="$(cd "${scriptDir}/.." && pwd)"

VOILA_NOTEBOOK="${repoRoot}/icesee_jupyter_book/icesee_jupyter_notebooks/run_center_voila.ipynb"
ICESHEET_NOTEBOOK="${repoRoot}/icesee_jupyter_book/icesee_jupyter_notebooks/icesheets_voila.ipynb"

BOOK_PORT=8081
VOILA_PORT=8866
ICESHEET_GUI_PORT=8870
ROUTER_PORT=8080

LOG_DIR="${repoRoot}/.service_logs"
PID_DIR="${repoRoot}/.service_pids"
mkdir -p "${LOG_DIR}" "${PID_DIR}"

if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
else
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi

BOOK_DIR="${repoRoot}/icesee_jupyter_book/_build/html"

echo "[ICESEE] Starting services in background..."
echo "[ICESEE] python=${PYTHON_BIN}"
echo "[ICESEE] repoRoot=${repoRoot}"
echo "[ICESEE] book=${BOOK_DIR}"

pkill -f "http.server --bind 127.0.0.1 ${BOOK_PORT}" 2>/dev/null || true
pkill -f "voila .*run_center_voila.ipynb" 2>/dev/null || true
pkill -f "voila .*icesheets_voila.ipynb" 2>/dev/null || true
pkill -f "icesee_router.py --listen-port ${ROUTER_PORT}" 2>/dev/null || true

(
  cd "${BOOK_DIR}"
  nohup "${PYTHON_BIN}" -m http.server --bind 127.0.0.1 "${BOOK_PORT}" \
    > "${LOG_DIR}/book.log" 2>&1 &
  echo $! > "${PID_DIR}/book.pid"
)

(
  cd "${repoRoot}"
  nohup "${PYTHON_BIN}" -m voila "${VOILA_NOTEBOOK}" \
    --no-browser \
    --Voila.ip=127.0.0.1 \
    --port="${VOILA_PORT}" \
    --Voila.base_url="/icesee-gui/" \
    > "${LOG_DIR}/icesee_gui.log" 2>&1 &
  echo $! > "${PID_DIR}/icesee_gui.pid"
)

(
  cd "${repoRoot}"
  nohup "${PYTHON_BIN}" -m voila "${ICESHEET_NOTEBOOK}" \
    --no-browser \
    --Voila.ip=127.0.0.1 \
    --port="${ICESHEET_GUI_PORT}" \
    --Voila.base_url="/icesheets/" \
    > "${LOG_DIR}/icesheets_gui.log" 2>&1 &
  echo $! > "${PID_DIR}/icesheets_gui.pid"
)

sleep 3

(
  cd "${repoRoot}"
  nohup "${PYTHON_BIN}" "${repoRoot}/bin/icesee_router.py" \
    --listen-port "${ROUTER_PORT}" \
    --book-port "${BOOK_PORT}" \
    --voila-port "${VOILA_PORT}" \
    --icesheet-port "${ICESHEET_GUI_PORT}" \
    > "${LOG_DIR}/router.log" 2>&1 &
  echo $! > "${PID_DIR}/router.pid"
)

sleep 2

echo "[ICESEE] Background services launched."
echo "[ICESEE] Logs: ${LOG_DIR}"
echo "[ICESEE] PIDs: ${PID_DIR}"
exit 0