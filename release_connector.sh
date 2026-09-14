#!/usr/bin/env bash
# =============================================================================
# CryoStack Connector -- generate the public release from the canonical store
# and promote it to the served directory.
#
#   canonical artifact store --> candidate/ (validated) --> /var/www/.../downloads/connectors/
#
# Run this AS THE RELEASE OWNER, WITHOUT sudo:
#
#   bash release_connector.sh
#
# The script escalates privilege itself, only for the steps that need it:
#   * the canonical store is resolved from the release owner's home (never
#     /root, even if the whole script is invoked under sudo);
#   * inspecting the store, building the candidate and verifying it all run
#     UNPRIVILEGED;
#   * ONLY the atomic promotion into the (root-owned) web root, and the nginx
#     reload, are run through sudo -- which may trigger the site's sudo/Duo
#     prompt the first time. That is expected.
#
# `sudo bash release_connector.sh` is also supported (SUDO_USER still resolves
# the owner + store to the invoking user), but is not the normal workflow.
#
# A failed candidate leaves the currently served release byte-for-byte
# unchanged. A failed swap rolls the previous live release back. Idempotent.
# A platform is dropped only via an explicit `unpublish`.
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

# Pin one interpreter, resolved as the invoking user, so the privileged step
# does not fall back to sudo's secure_path python.
PY="$(command -v python3 || true)"
[[ -n "$PY" ]] || PY="python3"

RELEASE_OWNER="$(cryostack_release_owner)"
RELEASE_HOME="$(cryostack_release_home)"
STORE="${CRYOSTACK_CONNECTOR_STORE:-$RELEASE_HOME/.cryostack/connector-artifacts}"

# When the WHOLE script was invoked under sudo, drop back to the release owner
# for the unprivileged steps so the store is read from the right home.
UNPRIV=()
if [[ "$(id -u)" -eq 0 && "$RELEASE_OWNER" != "root" ]]; then
  UNPRIV=(sudo -u "$RELEASE_OWNER" --)
  echo "[release] invoked as root; unprivileged steps run as '${RELEASE_OWNER}'"
fi

# Does the promotion need root? Only if we are not already root AND either the
# web root's parent is not writable, or an existing served / scratch tree holds
# a file we do not own (root-owned leftovers from earlier deployments).
PARENT="$(dirname "$CONNECTORS_DIR")"
NEED_ROOT=0
if [[ "$(id -u)" -ne 0 ]]; then
  mkdir -p "$PARENT" 2>/dev/null || true
  if [[ ! -w "$PARENT" ]]; then
    NEED_ROOT=1
  else
    for d in "$CONNECTORS_DIR" "${CONNECTORS_DIR}.release-new" "${CONNECTORS_DIR}.release-old"; do
      [[ -e "$d" ]] || continue
      if [[ -n "$(find "$d" \! -user "$(id -un)" -print -quit 2>/dev/null)" ]]; then
        NEED_ROOT=1
        break
      fi
    done
  fi
fi
PROMOTE_PRIV=()
[[ "$NEED_ROOT" -eq 1 ]] && PROMOTE_PRIV=(sudo)

# nginx -t / reload needs root unless we already are root.
NGINX_PRIV=()
[[ "$(id -u)" -ne 0 ]] && NGINX_PRIV=(sudo)

# Report the resolved identity/paths without doing anything (for operators and
# for testing the privilege boundary).
if [[ "${1:-}" == "--print-config" ]]; then
  echo "release_owner=${RELEASE_OWNER}"
  echo "release_home=${RELEASE_HOME}"
  echo "canonical_store=${STORE}"
  echo "served_dir=${CONNECTORS_DIR}"
  echo "privileged_promotion=$([[ ${#PROMOTE_PRIV[@]} -gt 0 ]] && echo yes || echo no)"
  exit 0
fi

echo "[release] release owner   : ${RELEASE_OWNER}"
echo "[release] canonical store : ${STORE}"
echo "[release] served dir      : ${CONNECTORS_DIR}"
"${UNPRIV[@]}" "$PY" "$STORE_TOOL" --store "$STORE" list

# ---- 1. candidate: fully unprivileged, in the owner's own temp dir --------
CAND_ROOT="$("${UNPRIV[@]}" mktemp -d)"
# shellcheck disable=SC2064
trap "${UNPRIV[*]} rm -rf '$CAND_ROOT'" EXIT
CAND="$CAND_ROOT/candidate"

echo "[release] building + verifying the release candidate ..."
"${UNPRIV[@]}" "$PY" "$STORE_TOOL"   --store "$STORE" build-candidate "$CAND"
"${UNPRIV[@]}" "$PY" "$MANIFEST_TOOL" verify "$CAND"
"${UNPRIV[@]}" "$PY" "$MANIFEST_TOOL" check-perms "$CAND"
echo "[release] candidate manifest:"
"${UNPRIV[@]}" sed 's/^/    /' "$CAND/manifest.json"

# ---- 2. promotion: the ONLY privileged file operation --------------------
# The candidate holds only what will become public; make it traversable so a
# privileged promotion (a different uid) can read it regardless of /tmp modes.
"${UNPRIV[@]}" chmod -R a+rX "$CAND_ROOT"

if [[ ${#PROMOTE_PRIV[@]} -gt 0 ]]; then
  echo "[release] promoting into ${CONNECTORS_DIR} (root-owned) -- escalating with sudo for this step"
fi
"${PROMOTE_PRIV[@]}" "$PY" "$STORE_TOOL" promote "$CAND" "$CONNECTORS_DIR"

# ---- 3. verify the LIVE tree before declaring success (read-only) --------
"$PY" "$MANIFEST_TOOL" verify "$CONNECTORS_DIR"
"$PY" "$MANIFEST_TOOL" check-perms "$CONNECTORS_DIR"

# The connector downloads are static files -- nginx serves the new versions on
# the next request with no reload. A reload is only a courtesy and must never
# fail an otherwise-successful release.
if command -v nginx >/dev/null 2>&1; then
  if "${NGINX_PRIV[@]}" nginx -t >/dev/null 2>&1 && "${NGINX_PRIV[@]}" systemctl reload nginx >/dev/null 2>&1; then
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
