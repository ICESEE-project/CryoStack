#!/usr/bin/env bash
set -euo pipefail

# This script lives in deployment/deploy_web_nginx/ ; its web/ and nginx/ dirs
# are the source of truth for the deployed static site.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WEB_SRC="${SCRIPT_DIR}/web"
NGINX_SRC="${SCRIPT_DIR}/nginx"
WEB_ROOT="${CRYOSTACK_WEB_ROOT:-/var/www/cryolauncher}"
NGINX_CONFD="${CRYOSTACK_NGINX_CONFD:-/etc/nginx/conf.d}"
PUBLIC_BASE="${CRYOSTACK_PUBLIC_BASE:-https://cryostack.eas.gatech.edu}"
# downloads/connectors/ is published + permission-hardened by release_connector.sh
CONNECTORS_REL="downloads/connectors"

echo "[ICESEE] Deploying web assets from ${WEB_SRC} ..."

sudo mkdir -p "${WEB_ROOT}"

# Sync web files. --delete keeps the deployed tree in sync with the repo, but
# connector distributables are published separately by release_connector.sh
# and must NOT be wiped by a web redeploy.
sudo rsync -av --delete \
  --exclude="/${CONNECTORS_REL}/***" \
  "${WEB_SRC}/" "${WEB_ROOT}/"

# ---------------------------------------------------------------------------
# rsync -a preserves the repo's source modes (0770 dirs / 0660 files under the
# repo's group-shared umask). The nginx worker is a different, unprivileged
# user, so without this it gets `open() ... (13: Permission denied)` -> 403.
# Enforce public-static modes on the subtrees THIS deploy owns only.
# ---------------------------------------------------------------------------
echo "[ICESEE] Enforcing public-static permissions under ${WEB_ROOT} ..."
sudo chmod 0755 "${WEB_ROOT}"
sudo find "${WEB_ROOT}" -path "${WEB_ROOT}/${CONNECTORS_REL}" -prune -o \
  -type d -exec chmod 0755 {} +
sudo find "${WEB_ROOT}" -path "${WEB_ROOT}/${CONNECTORS_REL}" -prune -o \
  -type f -exec chmod 0644 {} +
# the connectors dir itself must stay traversable; its contents are not ours
[ -d "${WEB_ROOT}/${CONNECTORS_REL}" ] && sudo chmod 0755 "${WEB_ROOT}/${CONNECTORS_REL}"

# SELinux: restore the expected web content context. Fatal if it fails while
# SELinux is active -- a wrong label silently 403s under Enforcing.
if command -v getenforce >/dev/null 2>&1 && [ "$(getenforce)" != "Disabled" ] \
   && command -v restorecon >/dev/null 2>&1; then
  echo "[ICESEE] Restoring SELinux web context ($(getenforce)) ..."
  if ! sudo restorecon -RF "${WEB_ROOT}"; then
    echo "[ICESEE][ERROR] restorecon failed for ${WEB_ROOT} -- the page may 403." >&2
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Verify the effective nginx worker can actually traverse + read the page.
# ---------------------------------------------------------------------------
NGINX_USER="$(sudo nginx -T 2>/dev/null | awk '/^[[:space:]]*user[[:space:]]/ {gsub(/;/,"",$2); print $2; exit}')"
NGINX_USER="${NGINX_USER:-nginx}"
echo "[ICESEE] Verifying readability as nginx worker '${NGINX_USER}' ..."

_fail=0
if ! sudo -u "${NGINX_USER}" test -x "${WEB_ROOT}/connect"; then
  echo "[ICESEE][ERROR] ${NGINX_USER} cannot traverse ${WEB_ROOT}/connect" >&2
  _fail=1
fi
for rel in connect/index.html connect/connect.js; do
  f="${WEB_ROOT}/${rel}"
  if [ ! -f "$f" ]; then
    echo "[ICESEE][ERROR] missing static asset: $f" >&2
    _fail=1
  elif ! sudo -u "${NGINX_USER}" test -r "$f"; then
    echo "[ICESEE][ERROR] ${NGINX_USER} cannot read $f" >&2
    namei -l "$f" >&2 || true
    _fail=1
  fi
done
[ "$_fail" -eq 0 ] || exit 1

# ---------------------------------------------------------------------------
# nginx config
# ---------------------------------------------------------------------------
echo "[ICESEE] Updating nginx config in ${NGINX_CONFD} ..."
# The repo ships exactly two files: 00-websocket-map.conf (the shared `map`
# block, loaded first) and icesee.conf (the single server definition).
sudo cp "${NGINX_SRC}"/*.conf "${NGINX_CONFD}/"
sudo chmod 0644 "${NGINX_CONFD}"/00-websocket-map.conf "${NGINX_CONFD}"/icesee.conf

# Disable any *earlier* CryoStack server block so there is no "conflicting
# server name" warning and no duplicate `map`. Only files we recognise as our
# own prior output; Certbot's files, default.conf and anything else are left.
for stale in cryolauncher.conf cryostack.conf icesee.conf.disabled; do
  f="${NGINX_CONFD}/${stale}"
  if [[ -e "$f" ]]; then
    echo "[ICESEE] disabling superseded ${stale} -> ${stale}.replaced-by-icesee-conf"
    sudo mv -f "$f" "${f}.replaced-by-icesee-conf"
  fi
done

OTHERS="$(grep -rlZ 'server_name[[:space:]]\+cryostack\.eas\.gatech\.edu' "${NGINX_CONFD}"/*.conf 2>/dev/null \
  | tr '\0' '\n' | grep -v '/icesee\.conf$' || true)"
if [[ -n "$OTHERS" ]]; then
  echo "[ICESEE][WARN] another conf.d file also declares server_name cryostack.eas.gatech.edu:"
  echo "$OTHERS" | sed 's/^/           /'
  echo "[ICESEE][WARN] run deployment/nginx_audit.sh and consolidate manually."
fi

# nginx -t is the hard gate: a bad config never goes live.
sudo nginx -t
sudo systemctl reload nginx

# ---------------------------------------------------------------------------
# Live HTTP smoke check. A query string must not change filesystem routing.
# ---------------------------------------------------------------------------
if [ "${CRYOSTACK_SKIP_SMOKE:-0}" != "1" ] && command -v curl >/dev/null 2>&1; then
  for path in "/connect/" "/connect/?app=icesheets"; do
    if curl -fsS "${PUBLIC_BASE}${path}" >/dev/null; then
      echo "[ICESEE] smoke OK  ${PUBLIC_BASE}${path}"
    else
      echo "[ICESEE][ERROR] smoke check failed: ${PUBLIC_BASE}${path}" >&2
      echo "[ICESEE][ERROR] check: sudo tail /var/log/nginx/error.log ; namei -l ${WEB_ROOT}/connect/index.html" >&2
      exit 1
    fi
  done
fi

echo "[ICESEE] Deployment complete."
