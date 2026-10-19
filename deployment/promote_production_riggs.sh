#!/usr/bin/env bash
# Validate and atomically publish an immutable RIGGS context release.
set -Eeuo pipefail

source_csv="${1:-}"
source_manifest="${2:-}"
dataset_root="${CRYOSTACK_RIGGS_DATASET_ROOT:-/home/bkyanjo3/cryostack-data/datasets/riggs}"
releases_root="${dataset_root}/releases"
current="${dataset_root}/current"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"

if [ -z "${source_csv}" ] || [ -z "${source_manifest}" ]; then
    echo "Usage: $0 RIGGS.csv RIGGS.manifest.json" >&2
    exit 2
fi
test -f "${source_csv}"
test -f "${source_manifest}"
source_csv="$(readlink -f -- "${source_csv}")"
source_manifest="$(readlink -f -- "${source_manifest}")"
source_root="$(dirname -- "${source_csv}")"

digest="$(env \
    CRYOSTACK_FROZEN_LEGACIES_STORAGE_ROOTS="${source_root}" \
    CRYOSTACK_FROZEN_LEGACIES_RIGGS_CSV="${source_csv}" \
    CRYOSTACK_FROZEN_LEGACIES_RIGGS_MANIFEST="${source_manifest}" \
    PYTHONPATH="${repo_root}" \
    "${PYTHON:-python3}" -c \
    'from icesee_jupyter_book.applications.frozen_legacies.riggs_context import riggs_collection
r = riggs_collection()
assert r["available"] and r["summary"]["stations"] > 0
print(r["metadata"]["sha256"])')"
[[ "${digest}" =~ ^[0-9a-f]{64}$ ]]

release="${releases_root}/riggs-${digest:0:16}"
install -d -m 0750 "${releases_root}"
install -d -m 0750 "${release}"
install -m 0640 "${source_csv}" "${release}/riggs_stations.csv"
install -m 0640 "${source_manifest}" "${release}/manifest.json"
link_tmp="${dataset_root}/.current.${digest:0:16}"
ln -sfn "${release}" "${link_tmp}"
mv -Tf "${link_tmp}" "${current}"
echo "Published verified production RIGGS release: ${release}"
echo "Current production RIGGS release: ${current}"
