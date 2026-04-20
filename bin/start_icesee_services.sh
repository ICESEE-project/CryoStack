#!/bin/sh
set -eu

scriptDir=$(dirname "$(readlink -f "$0")")
repoRoot="${scriptDir}/.."

cd "${repoRoot}"

BOOK_HTML="${repoRoot}/icesee_jupyter_book/_build/html/index.html"

if [ ! -f "${BOOK_HTML}" ]; then
    echo "[ICESEE] Built Jupyter Book not found. Building..."
    jupyter-book build icesee_jupyter_book/
fi

if [ ! -f "${BOOK_HTML}" ]; then
    echo "[ICESEE][ERROR] Failed to build Jupyter Book."
    exit 2
fi

echo "[ICESEE] Starting single GHUB app on 127.0.0.1:8080"
exec python "${scriptDir}/icesee_app.py"