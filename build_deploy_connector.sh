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
MANIFEST_TOOL="$REPO_ROOT/deployment/connector_manifest.py"

# The only artifact filenames CryoStack publishes (one per supported platform).
CANONICAL_ARTIFACTS=(
  "${APP_BASENAME}-linux-x86_64.tar.gz"
  "${APP_BASENAME}-macos-arm64.dmg"
  "${APP_BASENAME}-macos-x86_64.dmg"
  "${APP_BASENAME}-windows-x86_64.exe"
)

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

# ---- collect the canonical artifact set actually present ---------------
ARTIFACTS=()
for name in "${CANONICAL_ARTIFACTS[@]}"; do
  f="$PKG_DIR/$name"
  if [[ -f "$f" ]]; then
    [[ -s "$f" ]] || { echo "[deploy] ERROR: artifact is zero bytes: $f" >&2; exit 1; }
    ARTIFACTS+=( "$f" )
  fi
done

if [[ ${#ARTIFACTS[@]} -eq 0 ]]; then
  echo "[deploy] ERROR: no canonical ${APP_BASENAME}-* artifacts in $PKG_DIR" >&2
  echo "[deploy] expected one or more of:" >&2
  printf '  %s\n' "${CANONICAL_ARTIFACTS[@]}" >&2
  exit 1
fi

# ---- deployment is the authoritative manifest step -------------------
# Regenerate manifest.json + SHA256SUMS from the exact set above, then verify
# they agree with the files. A stale single-host manifest is replaced here.
echo "[deploy] regenerating manifest.json + SHA256SUMS from $PKG_DIR ..."
python3 "$MANIFEST_TOOL" generate "$PKG_DIR"
python3 "$MANIFEST_TOOL" verify "$PKG_DIR"

echo "[deploy] artifacts to publish:"
printf '  %s\n' "${ARTIFACTS[@]##*/}"

STAGE=( "${ARTIFACTS[@]}" "$PKG_DIR/manifest.json" "$PKG_DIR/SHA256SUMS" )
# Carry the build-metadata sidecars so a later re-deploy keeps the real
# build_at even without rebuilding.
shopt -s nullglob
STAGE+=( "$PKG_DIR"/*.build.json )
shopt -u nullglob

# ---- deploy -------------------------------------------------------------
# Order: copy -> fix permissions -> verify integrity + readability -> reload
# nginx. nginx is reloaded only after the artifacts are proven good.
publish_local() {
  local sudo=""
  [[ -w "$WEB_ROOT" || -w "$(dirname "$WEB_ROOT")" ]] || sudo="sudo"

  $sudo mkdir -p "$CONNECTORS_DIR"
  $sudo cp -f "${STAGE[@]}" "$CONNECTORS_DIR/"

  # Public-static permissions: dirs 0755, files 0644, along the served path.
  $sudo chmod 0755 "$WEB_ROOT" "$DOWNLOADS_DIR" "$CONNECTORS_DIR"
  $sudo find "$CONNECTORS_DIR" -type d -exec chmod 0755 {} +
  $sudo find "$CONNECTORS_DIR" -type f -exec chmod 0644 {} +

  echo "[deploy] verifying deployed artifacts + permissions ..."
  python3 "$MANIFEST_TOOL" verify "$CONNECTORS_DIR"
  python3 "$MANIFEST_TOOL" check-perms "$CONNECTORS_DIR"

  if command -v nginx >/dev/null 2>&1; then
    $sudo nginx -t && $sudo systemctl reload nginx
  else
    echo "[deploy] note: nginx not on PATH — reload it manually."
  fi
}

publish_remote() {
  local user_host="$DEPLOY_HOST"
  ssh "$user_host" "sudo mkdir -p '$CONNECTORS_DIR'"
  rsync -az --rsync-path="sudo rsync" "${STAGE[@]}" "$user_host:$CONNECTORS_DIR/"
  scp "$MANIFEST_TOOL" "$user_host:/tmp/cryostack_connector_manifest.py"
  ssh "$user_host" "\
    sudo chmod 0755 '$WEB_ROOT' '$DOWNLOADS_DIR' '$CONNECTORS_DIR' && \
    sudo find '$CONNECTORS_DIR' -type d -exec chmod 0755 {} + && \
    sudo find '$CONNECTORS_DIR' -type f -exec chmod 0644 {} + && \
    python3 /tmp/cryostack_connector_manifest.py verify '$CONNECTORS_DIR' && \
    python3 /tmp/cryostack_connector_manifest.py check-perms '$CONNECTORS_DIR' && \
    sudo nginx -t && sudo systemctl reload nginx && \
    rm -f /tmp/cryostack_connector_manifest.py"
}

if [[ -n "$DEPLOY_HOST" ]]; then
  echo "[deploy] publishing to remote host: $DEPLOY_HOST"
  publish_remote
else
  echo "[deploy] publishing locally to: $CONNECTORS_DIR"
  publish_local
fi

# ---- summary --------------------------------------------------------
echo
echo "=============================================================="
echo " Published CryoStack Connector artifacts"
echo "   deploy dir : $CONNECTORS_DIR"
echo "   public base: $PUBLIC_BASE/downloads/connectors/"
echo
for a in "${ARTIFACTS[@]}"; do
  echo "   $PUBLIC_BASE/downloads/connectors/$(basename "$a")"
done
echo
echo " manifest.json:"
sed 's/^/   /' "$PKG_DIR/manifest.json"
echo
echo " Verify over HTTP, e.g.:"
for a in "${ARTIFACTS[@]}"; do
  echo "   curl -sSIL '$PUBLIC_BASE/downloads/connectors/$(basename "$a")' | grep -Ei 'HTTP/|content-(type|length|disposition)'"
done
echo "   curl -sSL  '$PUBLIC_BASE/downloads/connectors/SHA256SUMS'"
echo "=============================================================="
