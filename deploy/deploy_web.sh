#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."

echo "[ICESEE] Deploying web assets..."

# Ensure target exists
sudo mkdir -p /var/www/cryolauncher

# Sync web files
rsync -av --delete deploy/web/ /var/www/cryolauncher/

echo "[ICESEE] Updating nginx config..."

# Copy nginx configs
sudo cp deploy/nginx/* /etc/nginx/conf.d/

# Test nginx config
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx

echo "[ICESEE] Deployment complete."
