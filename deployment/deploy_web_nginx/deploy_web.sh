#!/usr/bin/env bash
set -euo pipefail

# This script lives in deployment/deploy_web_nginx/ ; its web/ and nginx/ dirs
# are the source of truth for the deployed static site.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WEB_SRC="${SCRIPT_DIR}/web"
NGINX_SRC="${SCRIPT_DIR}/nginx"
WEB_ROOT="${CRYOSTACK_WEB_ROOT:-/var/www/cryolauncher}"
NGINX_CONFD="${CRYOSTACK_NGINX_CONFD:-/etc/nginx/conf.d}"

echo "[ICESEE] Deploying web assets from ${WEB_SRC} ..."

sudo mkdir -p "${WEB_ROOT}"

# Sync web files. --delete keeps the deployed tree in sync with the repo, but
# connector distributables are published separately by release_connector.sh
# and must NOT be wiped by a web redeploy.
sudo rsync -av --delete \
  --exclude='/downloads/connectors/***' \
  "${WEB_SRC}/" "${WEB_ROOT}/"

echo "[ICESEE] Updating nginx config in ${NGINX_CONFD} ..."

# The repo ships exactly two files: 00-websocket-map.conf (the shared
# `map` block, loaded first) and icesee.conf (the single server definition).
sudo cp "${NGINX_SRC}"/*.conf "${NGINX_CONFD}/"
sudo chmod 0644 "${NGINX_CONFD}"/00-websocket-map.conf "${NGINX_CONFD}"/icesee.conf

# Disable any *earlier* CryoStack server block so there is no
# "conflicting server name" warning and no duplicate `map`. We only ever
# touch files we recognise as our own prior output; Certbot's own files,
# default.conf and anything else are left alone.
for stale in cryolauncher.conf cryostack.conf icesee.conf.disabled; do
  f="${NGINX_CONFD}/${stale}"
  if [[ -e "$f" ]]; then
    echo "[ICESEE] disabling superseded ${stale} -> ${stale}.replaced-by-icesee-conf"
    sudo mv -f "$f" "${f}.replaced-by-icesee-conf"
  fi
done

# Warn (do not touch) if some other loaded file still claims our server_name.
OTHERS="$(grep -rlZ 'server_name[[:space:]]\+cryostack\.eas\.gatech\.edu' "${NGINX_CONFD}"/*.conf 2>/dev/null \
  | tr '\0' '\n' | grep -v '/icesee\.conf$' || true)"
if [[ -n "$OTHERS" ]]; then
  echo "[ICESEE][WARN] another conf.d file also declares server_name cryostack.eas.gatech.edu:"
  echo "$OTHERS" | sed 's/^/           /'
  echo "[ICESEE][WARN] run deployment/nginx_audit.sh and consolidate manually."
fi

# nginx -t gates the reload: a bad config never goes live.
sudo nginx -t
sudo systemctl reload nginx

echo "[ICESEE] Deployment complete."
