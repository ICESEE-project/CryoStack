#!/usr/bin/env bash

set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BOOK="${ROOT}/icesee_jupyter_book"
MAIN_BUILD="${BOOK}/_build/html"
TOC_DIR="${BOOK}/toc"

ORIGINAL_TOC="${BOOK}/_toc.yml"
TMP_ROOT="$(mktemp -d)"
BACKUP_TOC="${TMP_ROOT}/_toc.yml"

cp "${ORIGINAL_TOC}" "${BACKUP_TOC}"

cleanup() {
    cp "${BACKUP_TOC}" "${ORIGINAL_TOC}"
    rm -rf "${TMP_ROOT}"
}
trap cleanup EXIT

build_application() {
    local name="$1"
    local toc_file="$2"
    local source_subdir="$3"

    local slug
    slug="$(basename "${toc_file}" .yml)"

    local app_output="${TMP_ROOT}/${slug}"

    echo
    echo "=================================================="
    echo "Building ${name} documentation..."
    echo "=================================================="

    if [[ ! -f "${toc_file}" ]]; then
        echo "ERROR: TOC file not found: ${toc_file}" >&2
        return 1
    fi

    cp "${toc_file}" "${BOOK}/_toc.yml"

    rm -rf "${app_output}"

    jupyter-book build \
        "${BOOK}" \
        --path-output "${app_output}"

    local generated_dir="${app_output}/_build/html/${source_subdir}"
    local destination_dir="${MAIN_BUILD}/${source_subdir}"

    if [[ ! -d "${generated_dir}" ]]; then
        echo "ERROR: Expected documentation output was not generated:" >&2
        echo "       ${generated_dir}" >&2
        return 1
    fi

    mkdir -p "${destination_dir}"

    rm -rf "${destination_dir:?}/"*

    cp -a \
        "${generated_dir}/." \
        "${destination_dir}/"

    echo "${name} documentation copied to:"
    echo "  ${destination_dir}"
}

build_application \
    "CryoLauncher" \
    "${TOC_DIR}/cryolauncher.yml" \
    "applications/icesheets"

build_application \
    "ICESEE" \
    "${TOC_DIR}/icesee.yml" \
    "applications/icesee"

build_application \
    "Frozen Legacies" \
    "${TOC_DIR}/frozen_legacies.yml" \
    "applications/frozen_legacies"
    
echo
echo "=================================================="
echo "Application documentation build complete."
echo "=================================================="