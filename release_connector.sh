#!/usr/bin/env bash
# =============================================================================
# CryoStack Connector -- generate the public release from the canonical store
# and promote it to the served directory.
#
#   canonical artifact store --> candidate/ (validated) --> /var/www/.../downloads/connectors/
#
# Run on the release host after one or more `publish_connector_artifact.sh`.
# Idempotent. Preserves every registered platform; a candidate that fails
# validation never touches the live web tree.
#
#   bash release_connector.sh
#
# To drop a platform you must ask for it explicitly:
#   python3 deployment/connector_store.py unpublish <platform> && bash release_connector.sh
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

STORE_TOOL="$REPO_ROOT/deployment/connector_store.py"
MANIFEST_TOOL="$REPO_ROOT/deployment/connector_manifest.py"

STORE="${CRYOSTACK_CONNECTOR_STORE:-$HOME/.cryostack/connector-artifacts}"
WEB_ROOT="${CRYOSTACK_WEB_ROOT:-/var/www/cryolauncher}"
CONNECTORS_DIR="${WEB_ROOT}/downloads/connectors"
PUBLIC_BASE="${CRYOSTACK_PUBLIC_BASE:-https://cryostack.eas.gatech.edu}"

SUDO=""
[[ -w "$WEB_ROOT" || -w "$(dirname "$WEB_ROOT")" ]] || SUDO="sudo"

echo "[release] store        : $STORE"
echo "[release] served dir   : $CONNECTORS_DIR"
python3 "$STORE_TOOL" --store "$STORE" list

# ---- 1. build + validate a candidate (nothing served is touched yet) --
CAND_ROOT="$(mktemp -d)"
trap 'rm -rf "$CAND_ROOT"' EXIT
CAND="$CAND_ROOT/candidate"

echo "[release] building release candidate ..."
python3 "$STORE_TOOL" --store "$STORE" build-candidate "$CAND"
python3 "$MANIFEST_TOOL" verify "$CAND"
python3 "$MANIFEST_TOOL" check-perms "$CAND"

echo "[release] candidate manifest:"
sed 's/^/    /' "$CAND/manifest.json"

# ---- 2. promote (validated copy -> atomic swap into the served dir) ---
$SUDO mkdir -p "$CONNECTORS_DIR"
if [[ -n "$SUDO" ]]; then
  $SUDO env "PYTHONPATH=$REPO_ROOT/deployment" python3 "$STORE_TOOL" promote "$CAND" "$CONNECTORS_DIR"
else
  python3 "$STORE_TOOL" promote "$CAND" "$CONNECTORS_DIR"
fi

# ---- 3. re-verify the live tree, then reload nginx --------------------
python3 "$MANIFEST_TOOL" verify "$CONNECTORS_DIR"
python3 "$MANIFEST_TOOL" check-perms "$CONNECTORS_DIR"

if command -v nginx >/dev/null 2>&1; then
  $SUDO nginx -t && $SUDO systemctl reload nginx
else
  echo "[release] note: nginx not on PATH -- reload it manually."
fi

echo
echo "=============================================================="
echo " Published CryoStack Connector release"
for f in "$CONNECTORS_DIR"/CryoStack-Connector-*; do
  [[ -e "$f" ]] || continue
  echo "   $PUBLIC_BASE/downloads/connectors/$(basename "$f")"
done
echo
echo " Verify over HTTP:"
echo "   curl -sSL  '$PUBLIC_BASE/downloads/connectors/manifest.json'"
echo "   curl -sSL  '$PUBLIC_BASE/downloads/connectors/SHA256SUMS'"
for f in "$CONNECTORS_DIR"/CryoStack-Connector-*; do
  [[ -e "$f" ]] || continue
  echo "   curl -sSIL '$PUBLIC_BASE/downloads/connectors/$(basename "$f")' | grep -Ei 'HTTP/|content-(type|length|disposition)'"
done
echo "=============================================================="
