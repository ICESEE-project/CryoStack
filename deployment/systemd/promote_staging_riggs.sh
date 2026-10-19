#!/usr/bin/env bash
# Validate and publish an immutable RIGGS scientific-context release to staging.
# This never modifies the source files, production data, or nginx.
set -Eeuo pipefail

source_csv="${1:-}"
source_manifest="${2:-}"
dataset_root="/srv/cryostack-staging/datasets/riggs"
releases_root="${dataset_root}/releases"
current="${dataset_root}/current"
service_group="cryostack-app"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this reviewed staging promotion with sudo." >&2
    exit 2
fi
if [ -z "${source_csv}" ] || [ -z "${source_manifest}" ]; then
    echo "Usage: sudo $0 RIGGS.csv RIGGS.manifest.json" >&2
    exit 2
fi
test -f "${source_csv}"
test -f "${source_manifest}"
getent group "${service_group}" >/dev/null

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
if ! [[ "${digest}" =~ ^[0-9a-f]{64}$ ]]; then
    echo "RIGGS validation did not return a valid source digest." >&2
    exit 2
fi

release="${releases_root}/riggs-${digest:0:16}"
install -d -o root -g "${service_group}" -m 0750 "${releases_root}"
install -d -o root -g "${service_group}" -m 0750 "${release}"
install -o root -g "${service_group}" -m 0640 "${source_csv}" "${release}/riggs_stations.csv"
install -o root -g "${service_group}" -m 0640 "${source_manifest}" "${release}/manifest.json"

link_tmp="${dataset_root}/.current.${digest:0:16}"
ln -sfn "${release}" "${link_tmp}"
mv -Tf "${link_tmp}" "${current}"

echo "Published verified staging RIGGS release: ${release}"
echo "Current staging RIGGS release: ${current}"
echo "Production and the source intake were not changed."
