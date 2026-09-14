#!/usr/bin/env bash
# =============================================================================
# CryoStack Connector -- register this host's native build into the canonical
# artifact store.
#
#   native build output (dist/packages/) --> canonical artifact store
#
# Run this right after build_connector.sh on the machine that built the
# artifact. It NEVER writes to the web root; that is release_connector.sh's job.
#
# Local store (build host == release host, e.g. the GT VM):
#   bash publish_connector_artifact.sh
#
# Remote store (native builder is a separate Mac / Windows box):
#   export CRYOSTACK_RELEASE_HOST=deploy.example.edu      # ssh target
#   export CRYOSTACK_RELEASE_USER=cryostack               # optional ssh user
#   export CRYOSTACK_RELEASE_STORE=/srv/cryostack/connector-artifacts  # remote store
#   bash publish_connector_artifact.sh
#
# No hostnames are committed to the repository -- everything comes from the
# environment.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

PKG_DIR="$REPO_ROOT/dist/packages"
STORE_TOOL="$REPO_ROOT/deployment/connector_store.py"

APP_BASENAME="CryoStack-Connector"
CANONICAL=(
  "${APP_BASENAME}-linux-x86_64.tar.gz"
  "${APP_BASENAME}-macos-arm64.dmg"
  "${APP_BASENAME}-macos-x86_64.dmg"
  "${APP_BASENAME}-windows-x86_64.exe"
)

RELEASE_HOST="${CRYOSTACK_RELEASE_HOST:-}"
RELEASE_USER="${CRYOSTACK_RELEASE_USER:-}"
LOCAL_STORE="${CRYOSTACK_CONNECTOR_STORE:-$HOME/.cryostack/connector-artifacts}"
ALLOW_MISMATCH="${CRYOSTACK_ALLOW_PROTOCOL_MISMATCH:+--allow-protocol-mismatch}"

# The remote store path is resolved ON THE RELEASE HOST. Only forward an
# explicit CRYOSTACK_RELEASE_STORE; when it is unset the remote
# connector_store.py resolves its own default ($HOME/.cryostack/... on the
# release host) -- the builder's $HOME (e.g. /Users/... on a Mac) must never
# leak across.
REMOTE_STORE_OPT=()
if [[ -n "${CRYOSTACK_RELEASE_STORE:-}" ]]; then
  REMOTE_STORE_OPT=(--store "${CRYOSTACK_RELEASE_STORE}")
fi

# ---- find this host's freshly built artifact ---------------------------
ARTIFACT=""
for name in "${CANONICAL[@]}"; do
  f="$PKG_DIR/$name"
  if [[ -f "$f" && -s "$f" && -f "$f.build.json" ]]; then
    if [[ -n "$ARTIFACT" ]]; then
      echo "[publish] ERROR: more than one artifact+sidecar in $PKG_DIR." >&2
      echo "[publish] Clean dist/packages/ and rebuild a single platform." >&2
      exit 1
    fi
    ARTIFACT="$f"
  fi
done

if [[ -z "$ARTIFACT" ]]; then
  echo "[publish] ERROR: no <artifact> + <artifact>.build.json pair in $PKG_DIR." >&2
  echo "[publish] Run build_connector.sh on this platform first." >&2
  exit 1
fi
SIDECAR="${ARTIFACT}.build.json"
echo "[publish] artifact : $(basename "$ARTIFACT")"
echo "[publish] sidecar  : $(basename "$SIDECAR")"

# ---- register ---------------------------------------------------------
if [[ -z "$RELEASE_HOST" ]]; then
  echo "[publish] registering into local store: $LOCAL_STORE"
  python3 "$STORE_TOOL" --store "$LOCAL_STORE" register "$ARTIFACT" "$SIDECAR" $ALLOW_MISMATCH
  python3 "$STORE_TOOL" --store "$LOCAL_STORE" list
else
  SSH_TARGET="${RELEASE_USER:+$RELEASE_USER@}$RELEASE_HOST"
  if [[ ${#REMOTE_STORE_OPT[@]} -gt 0 ]]; then
    echo "[publish] sending to release host: $SSH_TARGET  (store: ${CRYOSTACK_RELEASE_STORE})"
  else
    echo "[publish] sending to release host: $SSH_TARGET  (store: release-host default)"
  fi
  REMOTE_TMP="$(ssh "$SSH_TARGET" 'mktemp -d')"
  # shellcheck disable=SC2064
  trap "ssh '$SSH_TARGET' 'rm -rf \"$REMOTE_TMP\"'" EXIT
  scp "$ARTIFACT" "$SIDECAR" "$SSH_TARGET:$REMOTE_TMP/"
  scp "$STORE_TOOL" "$REPO_ROOT/deployment/connector_manifest.py" "$SSH_TARGET:$REMOTE_TMP/"

  REMOTE_STORE_STR=""
  [[ ${#REMOTE_STORE_OPT[@]} -gt 0 ]] && REMOTE_STORE_STR="--store $(printf '%q' "${CRYOSTACK_RELEASE_STORE}")"
  ssh "$SSH_TARGET" "python3 '$REMOTE_TMP/connector_store.py' ${REMOTE_STORE_STR} \
      register '$REMOTE_TMP/$(basename "$ARTIFACT")' '$REMOTE_TMP/$(basename "$SIDECAR")' $ALLOW_MISMATCH \
    && python3 '$REMOTE_TMP/connector_store.py' ${REMOTE_STORE_STR} list"
fi

echo
echo "[publish] done. On the release host, run:  bash release_connector.sh"
