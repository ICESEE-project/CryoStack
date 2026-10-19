#!/usr/bin/env bash
# Verify the SPRI navigation intake and publish an immutable staging release.
# This never removes the source archive or changes production.
set -Eeuo pipefail

source_root="${1:-/scratch/cryostack-development/incoming/navigation/RadarFilmStudio}"
manifest="${2:-/scratch/cryostack-development/incoming/navigation/RadarFilmStudio.manifest.json}"
dataset_root="/srv/cryostack-staging/datasets/spri"
releases_root="${dataset_root}/navigation-releases"
current="${dataset_root}/navigation-current"
flights=(125 126 127 128 137 138 139 141 143 149)

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this reviewed staging promotion with sudo." >&2
    exit 2
fi
test -d "${source_root}"
test -f "${manifest}"
getent passwd cryostack-app >/dev/null

archive_sha="$(${PYTHON:-python3} - "${source_root}" "${manifest}" "${flights[@]}" <<'PY'
import hashlib, json, sys
from pathlib import Path

root, manifest_path = map(Path, sys.argv[1:3])
wanted = set(sys.argv[3:])
document = json.loads(manifest_path.read_text(encoding="utf-8"))
if document.get("schema") != "cryostack.frozen_legacies.navigation_manifest":
    raise SystemExit("Unexpected navigation manifest schema.")
records = {str(item.get("flight")): item for item in document.get("files", [])}
if set(records).intersection(wanted) != wanted:
    raise SystemExit("Manifest does not contain every approved staging flight.")
for flight in sorted(wanted, key=int):
    path = root / f"{flight}.csv"
    if not path.is_file():
        raise SystemExit(f"Missing approved flight {flight}.")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != records[flight].get("sha256"):
        raise SystemExit(f"Checksum mismatch for flight {flight}.")
print(str(document.get("source_sha256", ""))[:16])
PY
)"
if ! [[ "${archive_sha}" =~ ^[0-9a-f]{16}$ ]]; then
    echo "Manifest has no valid source archive digest." >&2
    exit 2
fi

release="${releases_root}/nav-${archive_sha}"
install -d -o root -g cryostack-app -m 0750 "${releases_root}"
install -d -o root -g cryostack-app -m 0750 "${release}"
for flight in "${flights[@]}"; do
    install -o root -g cryostack-app -m 0640 \
        "${source_root}/${flight}.csv" "${release}/${flight}.csv"
done
install -o root -g cryostack-app -m 0640 "${manifest}" "${release}/manifest.json"

link_tmp="${dataset_root}/.navigation-current.${archive_sha}"
ln -sfn "${release}" "${link_tmp}"
mv -Tf "${link_tmp}" "${current}"

echo "Published verified staging navigation release: ${release}"
echo "Current staging navigation: ${current}"
echo "Production and the scratch intake were not changed."
