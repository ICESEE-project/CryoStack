#!/usr/bin/env bash
# =============================================================================
# CryoStack Connector -- generate the public release from the canonical store
# and promote it to the served directory.
#
#   canonical artifact store --> candidate/ (validated) --> /var/www/.../downloads/connectors/
#
# Run this AS THE RELEASE OWNER, without sudo:
#
#   bash release_connector.sh
#
# The script manages the privilege boundary itself:
#   * the canonical store is resolved from the release owner's home (never
#     /root, even if the script is invoked under sudo);
#   * candidate generation + all verification run unprivileged;
#   * only the atomic promotion into the served directory is privileged, and
#     that escalation is scoped to the connectors directory.
#
# A failed candidate leaves the currently served release byte-for-byte
# unchanged. Idempotent: re-running with the same store re-publishes the same
# release. A platform is dropped only via an explicit `unpublish`.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"
# shellcheck source=deployment/release_env.sh
source "$REPO_ROOT/deployment/release_env.sh"

STORE_TOOL="$REPO_ROOT/deployment/connector_store.py"
MANIFEST_TOOL="$REPO_ROOT/deployment/connector_manifest.py"

WEB_ROOT="${CRYOSTACK_WEB_ROOT:-/var/www/cryolauncher}"
CONNECTORS_DIR="${WEB_ROOT}/downloads/connectors"
PUBLIC_BASE="${CRYOSTACK_PUBLIC_BASE:-https://cryostack.eas.gatech.edu}"

RELEASE_OWNER="$(cryostack_release_owner)"
RELEASE_HOME="$(cryostack_release_home)"
STORE="${CRYOSTACK_CONNECTOR_STORE:-$RELEASE_HOME/.cryostack/connector-artifacts}"

# Unprivileged steps run as the release owner even when the script is invoked
# via sudo, so the store is read from the right home.
UNPRIV=()
if [[ "$(id -u)" -eq 0 && "$RELEASE_OWNER" != "root" ]]; then
  UNPRIV=(sudo -u "$RELEASE_OWNER" --)
  echo "[release] invoked as root; unprivileged steps run as '${RELEASE_OWNER}'"
fi

echo "[release] release owner  : ${RELEASE_OWNER}"
echo "[release] canonical store : ${STORE}"
echo "[release] served dir      : ${CONNECTORS_DIR}"
"${UNPRIV[@]}" python3 "$STORE_TOOL" --store "$STORE" list

# ---- 1. candidate: fully unprivileged, in the owner's own temp dir --------
CAND_ROOT="$("${UNPRIV[@]}" mktemp -d)"
# shellcheck disable=SC2064
trap "${UNPRIV[*]} rm -rf '$CAND_ROOT'" EXIT
CAND="$CAND_ROOT/candidate"

echo "[release] building + verifying the release candidate ..."
"${UNPRIV[@]}" python3 "$STORE_TOOL"   --store "$STORE" build-candidate "$CAND"
"${UNPRIV[@]}" python3 "$MANIFEST_TOOL" verify "$CAND"
"${UNPRIV[@]}" python3 "$MANIFEST_TOOL" check-perms "$CAND"
echo "[release] candidate manifest:"
"${UNPRIV[@]}" sed 's/^/    /' "$CAND/manifest.json"

# ---- 2. promotion: the ONLY privileged step, scoped to the connectors dir -
PARENT="$(dirname "$CONNECTORS_DIR")"
PROMOTE=(python3)
if [[ "$(id -u)" -eq 0 ]]; then
  mkdir -p "$PARENT"
elif mkdir -p "$PARENT" 2>/dev/null && [[ -w "$PARENT" ]]; then
  :
else
  PROMOTE=(sudo python3)
  echo "[release] promotion needs root for ${PARENT} -> using sudo for this step only"
  sudo mkdir -p "$PARENT"
fi
"${PROMOTE[@]}" "$STORE_TOOL" promote "$CAND" "$CONNECTORS_DIR"

# ---- 3. verify the LIVE tree before declaring success (read-only) --------
python3 "$MANIFEST_TOOL" verify "$CONNECTORS_DIR"
python3 "$MANIFEST_TOOL" check-perms "$CONNECTORS_DIR"

# The connector downloads are static files -- nginx serves the new versions on
# the next request with no reload. A reload is only a courtesy (open-file cache)
# and must never fail an otherwise-successful release.
if command -v nginx >/dev/null 2>&1; then
  NG=(nginx); SC=(systemctl reload nginx)
  [[ "$(id -u)" -ne 0 ]] && { NG=(sudo nginx); SC=(sudo systemctl reload nginx); }
  if "${NG[@]}" -t >/dev/null 2>&1 && "${SC[@]}" >/dev/null 2>&1; then
    echo "[release] nginx reloaded"
  else
    echo "[release] note: could not reload nginx (privileges / config) -- static files are already live."
  fi
fi

# ---- summary ------------------------------------------------------------
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
