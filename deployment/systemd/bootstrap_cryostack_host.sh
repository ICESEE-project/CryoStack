#!/usr/bin/env bash
# Create the local CryoStack service identity and empty host directories.
# This deliberately does not install units, copy data, alter mounts, or start
# services. Run as root after reviewing the selected identity with operators.
set -Eeuo pipefail

service_user="${CRYOSTACK_SERVICE_USER:-cryostack-app}"
service_group="${CRYOSTACK_SERVICE_GROUP:-cryostack-app}"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this reviewed bootstrap with sudo." >&2
    exit 2
fi

if ! getent group "${service_group}" >/dev/null; then
    groupadd --system "${service_group}"
fi

if ! getent passwd "${service_user}" >/dev/null; then
    useradd \
        --system \
        --gid "${service_group}" \
        --home-dir /var/lib/cryostack \
        --create-home \
        --shell /sbin/nologin \
        --comment "CryoStack application service" \
        "${service_user}"
fi

install -d -o root -g "${service_group}" -m 0750 /etc/cryostack
install -d -o root -g "${service_group}" -m 0750 /opt/cryostack
install -d -o root -g "${service_group}" -m 0750 /opt/cryostack/releases
install -d -o "${service_user}" -g "${service_group}" -m 0750 /srv/cryostack
install -d -o "${service_user}" -g "${service_group}" -m 0750 /srv/cryostack/workspace
install -d -o "${service_user}" -g "${service_group}" -m 0750 /srv/cryostack-staging
install -d -o "${service_user}" -g "${service_group}" -m 0750 /scratch/cryostack

for name in build-cache test-runs working staging-cache; do
    install -d -o "${service_user}" -g "${service_group}" -m 0750 \
        "/scratch/cryostack/${name}"
done

echo "CryoStack service identity:"
id "${service_user}"
echo "Created empty service, staging, and scratch directories."
echo "No services, mounts, ACLs, or production data were changed."
