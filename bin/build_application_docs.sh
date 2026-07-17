#!/usr/bin/env bash

set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BOOK="${ROOT}/icesee_jupyter_book"
MAIN_BUILD="${BOOK}/_build/html"
TMP_DIR="$(mktemp -d)"
ORIGINAL_TOC="${BOOK}/_toc.yml"
BACKUP_TOC="${TMP_DIR}/_toc.yml"

cp "${ORIGINAL_TOC}" "${BACKUP_TOC}"

cleanup() {
    cp "${BACKUP_TOC}" "${ORIGINAL_TOC}"
    rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

cat > "${BOOK}/_toc.yml" <<'EOF'
format: jb-book
root: index

parts:
  - chapters:
      - file: applications/icesheets/getting_started
      - file: applications/icesheets/user_manual
      - file: applications/icesheets/resources
EOF

jupyter-book build "${BOOK}" --path-output "${TMP_DIR}"

mkdir -p "${MAIN_BUILD}/applications/icesheets"

cp -a \
  "${TMP_DIR}/_build/html/applications/icesheets/." \
  "${MAIN_BUILD}/applications/icesheets/"

echo "CryoLauncher documentation pages copied into the main build."