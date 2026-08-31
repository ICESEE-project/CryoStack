#!/usr/bin/env bash
# =============================================================================
# CryoStack Connector — build (this host) and publish every available artifact
# to the public /downloads/connectors/ route.
#
#   build_connector.sh              -> builds this host's platform artifact
#   dist/packages/                  -> all artifacts (this host + any copied in
#                                     from a Mac / Windows build)
#   <web-root>/downloads/connectors/ -> served at
#                                     https://<host>/downloads/connectors/
#
# The GT deployment builds and serves on the same host, so the default deploy
# is a local copy into the nginx web root. Set CRYOSTACK_DEPLOY_HOST to rsync
# to a separate web host instead.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

APP_BASENAME="CryoStack-Connector"
PKG_DIR="$REPO_ROOT/dist/packages"

# Web root nginx serves /downloads/ from (see deployment/deploy_web_nginx/nginx).
WEB_ROOT="${CRYOSTACK_WEB_ROOT:-/var/www/cryolauncher}"
DOWNLOADS_DIR="${WEB_ROOT}/downloads"
CONNECTORS_DIR="${DOWNLOADS_DIR}/connectors"
PUBLIC_BASE="${CRYOSTACK_PUBLIC_BASE:-https://cryostack.eas.gatech.edu}"

DEPLOY_HOST="${CRYOSTACK_DEPLOY_HOST:-}"     # empty -> local copy
SKIP_BUILD="${CRYOSTACK_SKIP_BUILD:-0}"      # 1 -> deploy whatever is in PKG_DIR

# Old pre-rename download paths are redirected to the new ones by nginx
# (deployment/deploy_web_nginx/nginx/icesee.conf), so no filesystem aliases
# are needed here and a web redeploy cannot strand them.

# ---- build this host's artifact -----------------------------------------
if [[ "$SKIP_BUILD" != "1" ]]; then
  echo "[deploy] building this host's connector artifact..."
  bash "$REPO_ROOT/build_connector.sh"
else
  echo "[deploy] CRYOSTACK_SKIP_BUILD=1 -> deploying existing artifacts only"
fi

# ---- collect artifacts ------------------------------------------------
shopt -s nullglob
ARTIFACTS=( "$PKG_DIR/${APP_BASENAME}"-*.dmg
            "$PKG_DIR/${APP_BASENAME}"-*.tar.gz
            "$PKG_DIR/${APP_BASENAME}"-*.exe )
shopt -u nullglob

if [[ ${#ARTIFACTS[@]} -eq 0 ]]; then
  echo "[deploy] ERROR: no CryoStack-Connector-* artifacts in $PKG_DIR" >&2
  exit 1
fi

for a in "${ARTIFACTS[@]}"; do
  [[ -s "$a" ]] || { echo "[deploy] ERROR: artifact is empty: $a" >&2; exit 1; }
done

# Regenerate SHA256SUMS from what we are actually shipping.
( cd "$PKG_DIR"
  : > SHA256SUMS
  for a in "${ARTIFACTS[@]}"; do
    b="$(basename "$a")"
    if command -v sha256sum >/dev/null 2>&1; then
      sha256sum "$b" >> SHA256SUMS
    else
      shasum -a 256 "$b" >> SHA256SUMS
    fi
  done
  sort -o SHA256SUMS SHA256SUMS )

echo "[deploy] artifacts to publish:"
printf '  %s\n' "${ARTIFACTS[@]##*/}"

# ---- deploy -------------------------------------------------------------
publish_local() {
  command -v nginx >/dev/null 2>&1 || echo "[deploy] warning: nginx not found on PATH"
  local sudo=""
  [[ -w "$WEB_ROOT" ]] || sudo="sudo"

  $sudo mkdir -p "$CONNECTORS_DIR"
  for a in "${ARTIFACTS[@]}"; do
    $sudo cp -f "$a" "$CONNECTORS_DIR/"
  done
  $sudo cp -f "$PKG_DIR/SHA256SUMS" "$CONNECTORS_DIR/SHA256SUMS"
  [[ -f "$PKG_DIR/manifest.json" ]] && $sudo cp -f "$PKG_DIR/manifest.json" "$CONNECTORS_DIR/manifest.json"

  if command -v nginx >/dev/null 2>&1; then
    $sudo nginx -t && $sudo systemctl reload nginx
  fi
}

publish_remote() {
  local user_host="$DEPLOY_HOST"
  ssh "$user_host" "sudo mkdir -p '$CONNECTORS_DIR'"
  rsync -avz --rsync-path="sudo rsync" "${ARTIFACTS[@]}" \
        "$PKG_DIR/SHA256SUMS" \
        "$user_host:$CONNECTORS_DIR/"
  [[ -f "$PKG_DIR/manifest.json" ]] && \
    rsync -avz --rsync-path="sudo rsync" "$PKG_DIR/manifest.json" "$user_host:$CONNECTORS_DIR/"
  ssh "$user_host" "sudo nginx -t && sudo systemctl reload nginx"
}

if [[ -n "$DEPLOY_HOST" ]]; then
  echo "[deploy] publishing to remote host: $DEPLOY_HOST"
  publish_remote
  VERIFY_HOST="$DEPLOY_HOST"
else
  echo "[deploy] publishing locally to: $CONNECTORS_DIR"
  publish_local
  VERIFY_HOST="(local)"
fi

# ---- verify ---------------------------------------------------------
echo
echo "=============================================================="
echo " Published CryoStack Connector artifacts"
echo "   deploy dir : $CONNECTORS_DIR"
echo "   public base: $PUBLIC_BASE/downloads/connectors/"
echo
for a in "${ARTIFACTS[@]}"; do
  b="$(basename "$a")"
  echo "   $PUBLIC_BASE/downloads/connectors/$b"
done
echo
echo " SHA256SUMS:"
sed 's/^/   /' "$PKG_DIR/SHA256SUMS"
echo
echo " Verify from the web host, e.g.:"
for a in "${ARTIFACTS[@]}"; do
  b="$(basename "$a")"
  echo "   curl -sSIL '$PUBLIC_BASE/downloads/connectors/$b' | grep -Ei 'HTTP/|content-(type|length|disposition)'"
done
echo "=============================================================="
