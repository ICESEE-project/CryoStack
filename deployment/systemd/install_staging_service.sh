#!/usr/bin/env bash
# Install an isolated localhost-only CryoStack staging service.
# Production processes, nginx routes, databases, and workspaces are untouched.
set -Eeuo pipefail

repo="${1:-/home/bkyanjo3/CryoLauncher}"
python_bin="${CRYOSTACK_PYTHON:-/home/bkyanjo3/.icesee_conda/envs/icesee1-dev/bin/python}"
service_user="cryostack-app"
service_group="cryostack-app"
release_root="/opt/cryostack/staging-current"
state_root="/srv/cryostack-staging/state"
env_file="/etc/cryostack/staging.env"
unit_source="${repo}/deployment/systemd/cryostack-staging.service"
unit_target="/etc/systemd/system/cryostack-staging.service"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this reviewed installer with sudo." >&2
    exit 2
fi
getent passwd "${service_user}" >/dev/null
test -x "${python_bin}"
test -f "${unit_source}"

# Permit only traversal of the operator home and read/execute access to the
# existing Python runtime. Application code is copied to /opt below.
setfacl -m "u:${service_user}:x" /home/bkyanjo3
setfacl -m "u:${service_user}:x" /home/bkyanjo3/.icesee_conda
setfacl -m "u:${service_user}:x" /home/bkyanjo3/.icesee_conda/envs
setfacl -R -m "u:${service_user}:rX" /home/bkyanjo3/.icesee_conda/envs/icesee1-dev

install -d -o root -g "${service_group}" -m 0750 "${release_root}"
rsync -a --delete \
    --exclude '.git' \
    --exclude '.pytest_cache/' \
    --exclude '__pycache__/' \
    --exclude '/build/' \
    --exclude '/dist/' \
    --exclude '/var/' \
    --exclude '/users/' \
    --exclude '*.log' \
    "${repo}/" "${release_root}/"
chown -R root:"${service_group}" "${release_root}"
find "${release_root}" -type d -exec chmod 0750 {} +
find "${release_root}" -type f -exec chmod 0640 {} +
chmod 0750 "${release_root}/bin/icesee_app.py"

install -d -o "${service_user}" -g "${service_group}" -m 0700 "${state_root}"
install -d -o "${service_user}" -g "${service_group}" -m 0700 \
    /srv/cryostack-staging/datasets

relay_token="$(openssl rand -hex 32)"
umask 0027
cat >"${env_file}" <<EOF
CRYOSTACK_HOST=127.0.0.1
CRYOSTACK_PORT=18080
CRYOSTACK_RUN_CENTER_PORT=18866
CRYOSTACK_ICESHEETS_PORT=18870
CRYOSTACK_DATA_ROOT=${state_root}
CRYOSTACK_REQUIRE_DURABLE_STORAGE=1
CRYOSTACK_FROZEN_LEGACIES_STORAGE_ROOTS=/srv/cryostack-staging/datasets
CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_ROOT=/srv/cryostack-staging/datasets/spri/navigation-current
CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_FLIGHTS=125,126,127,128,137,138,139,141,143,149
CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_DATASET=frozen-legacies-spri-navigation
CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_TITLE="SPRI archival radar navigation"
CRYOSTACK_FROZEN_LEGACIES_AUTOMATIC_PICKER=lyra
CRYOSTACK_RELAY_CONTROL_TOKEN=${relay_token}
EOF
if [ -L /srv/cryostack-staging/datasets/riggs/current ]; then
    cat >>"${env_file}" <<'EOF'
CRYOSTACK_FROZEN_LEGACIES_RIGGS_CSV=/srv/cryostack-staging/datasets/riggs/current/riggs_stations.csv
CRYOSTACK_FROZEN_LEGACIES_RIGGS_MANIFEST=/srv/cryostack-staging/datasets/riggs/current/manifest.json
EOF
fi
chown root:"${service_group}" "${env_file}"
chmod 0640 "${env_file}"

if [ ! -f "${state_root}/.cryostack-volume.json" ]; then
    runuser -u "${service_user}" -- env \
        CRYOSTACK_DATA_ROOT="${state_root}" \
        "${python_bin}" "${release_root}/deployment/cryostack_storage.py" \
        init-volume "${state_root}" \
        --attest "isolated staging state on VM XFS; not production or CEDAR" \
        --operator "staging-installer"
fi

install -o root -g root -m 0644 "${unit_source}" "${unit_target}"
systemctl daemon-reload
systemctl enable cryostack-staging.service
systemctl restart cryostack-staging.service

echo "Installed localhost-only staging service."
echo "Gateway: http://127.0.0.1:18080"
echo "Production services and nginx were not changed."
systemctl --no-pager --full status cryostack-staging.service || true
