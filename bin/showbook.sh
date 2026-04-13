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

if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
else
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi

find_book_html_dir() {
  local primary="${repoRoot}/icesee_jupyter_book/_build/html"

  if [ -d "${primary}" ] && [ -f "${primary}/index.html" ]; then
    echo "${primary}"
    return 0
  fi

  local found
  found="$(find "${repoRoot}" -type d -path "*/_build/html" 2>/dev/null | while read -r d; do
    if [ -f "$d/index.html" ]; then
      echo "$d"
      break
    fi
  done)"

  if [ -n "${found}" ]; then
    echo "${found}"
    return 0
  fi

  return 1
}

find_run_center_html() {
  local book_dir="$1"
  local target="${book_dir}/icesee_jupyter_notebooks/run_center.html"

  if [ -f "${target}" ]; then
    echo "${target}"
    return 0
  fi

  local found
  found="$(find "${book_dir}" -type f -name "run_center.html" 2>/dev/null | head -n 1)"
  if [ -n "${found}" ]; then
    echo "${found}"
    return 0
  fi

  return 1
}

cleanup() {
  jobs -p | xargs -r kill 2>/dev/null || true
}
trap cleanup EXIT INT TERM

BOOK_DIR="$(find_book_html_dir)" || {
  echo "[ICESEE][ERROR] Could not locate built book HTML under ${repoRoot}"
  exit 2
}

RUN_CENTER_HTML="$(find_run_center_html "${BOOK_DIR}")" || {
  echo "[ICESEE][ERROR] Could not locate run_center.html inside ${BOOK_DIR}"
  exit 2
}

echo "[ICESEE] repoRoot=${repoRoot}"
echo "[ICESEE] book=${BOOK_DIR}"
echo "[ICESEE] run_center=${RUN_CENTER_HTML}"
echo "[ICESEE] voila notebook=${VOILA_NOTEBOOK}"
echo "[ICESEE] icesheet notebook=${ICESHEET_NOTEBOOK}"
echo "[ICESEE] python=${PYTHON_BIN}"

if [ ! -f "${VOILA_NOTEBOOK}" ]; then
  echo "[ICESEE][ERROR] Voilà notebook not found: ${VOILA_NOTEBOOK}"
  exit 2
fi

if [ ! -f "${ICESHEET_NOTEBOOK}" ]; then
  echo "[ICESEE][ERROR] Ice-sheet Voilà notebook not found: ${ICESHEET_NOTEBOOK}"
  exit 2
fi

echo "[ICESEE] Starting static book on 127.0.0.1:${BOOK_PORT}"
(
  cd "${BOOK_DIR}"
  exec "${PYTHON_BIN}" -m http.server --bind 127.0.0.1 "${BOOK_PORT}"
) &
BOOK_PID=$!

echo "[ICESEE] Starting ICESEE GUI Voilà on 127.0.0.1:${VOILA_PORT}"
(
  cd "${repoRoot}"
  exec "${PYTHON_BIN}" -m voila "${VOILA_NOTEBOOK}" \
    --no-browser \
    --Voila.ip=127.0.0.1 \
    --port="${VOILA_PORT}" \
    --Voila.base_url="/icesee-gui/"
) &
VOILA_PID=$!

echo "[ICESEE] Starting Ice-Sheet Modeling GUI Voilà on 127.0.0.1:${ICESHEET_GUI_PORT}"
(
  cd "${repoRoot}"
  exec "${PYTHON_BIN}" -m voila "${ICESHEET_NOTEBOOK}" \
    --no-browser \
    --Voila.ip=127.0.0.1 \
    --port="${ICESHEET_GUI_PORT}" \
    --Voila.base_url="/icesheets/"
) &
ICESHEET_PID=$!

echo "[ICESEE] Starting router on 127.0.0.1:${ROUTER_PORT}"
(
  cd "${repoRoot}"
  exec "${PYTHON_BIN}" "${repoRoot}/bin/icesee_router.py" \
    --listen-port "${ROUTER_PORT}" \
    --book-port "${BOOK_PORT}" \
    --voila-port "${VOILA_PORT}" \
    --icesheet-port "${ICESHEET_GUI_PORT}"
) &
ROUTER_PID=$!

echo
echo "[ICESEE] Services"
echo "  Book:                    http://127.0.0.1:${ROUTER_PORT}/"
echo "  ICESEE GUI:              http://127.0.0.1:${ROUTER_PORT}/icesee-gui/"
echo "  Ice-Sheet Modeling GUI:  http://127.0.0.1:${ROUTER_PORT}/icesheets/"
echo

wait "${BOOK_PID}" "${VOILA_PID}" "${ICESHEET_PID}" "${ROUTER_PID}"