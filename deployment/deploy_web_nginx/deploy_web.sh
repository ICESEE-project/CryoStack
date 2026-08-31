#!/usr/bin/env bash
set -euo pipefail

# This script lives in deployment/deploy_web_nginx/ ; its web/ and nginx/ dirs
# are the source of truth for the deployed static site.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WEB_SRC="${SCRIPT_DIR}/web"
NGINX_SRC="${SCRIPT_DIR}/nginx"
WEB_ROOT="${CRYOSTACK_WEB_ROOT:-/var/www/cryolauncher}"

echo "[ICESEE] Deploying web assets from ${WEB_SRC} ..."

sudo mkdir -p "${WEB_ROOT}"

# Sync web files. --delete keeps the deployed tree in sync with the repo, but
# connector distributables are published separately by build_deploy_connector.sh
# and must NOT be wiped by a web redeploy.
sudo rsync -av --delete \
  --exclude='/downloads/connectors/***' \
  "${WEB_SRC}/" "${WEB_ROOT}/"

echo "[ICESEE] Updating nginx config..."

sudo cp "${NGINX_SRC}"/* /etc/nginx/conf.d/

# Test nginx config
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx

echo "[ICESEE] Deployment complete."
