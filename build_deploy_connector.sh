#!/usr/bin/env bash
# =============================================================================
# CryoStack Connector -- single-host convenience wrapper.
#
# For the common case where one machine both builds and serves (the GT VM):
#
#   build_connector.sh            native build            -> dist/packages/
#   publish_connector_artifact.sh register (local store)  -> <store>/<platform>/
#   release_connector.sh          generate + promote      -> <web-root>/downloads/connectors/
#
# This script just runs those three in order. For multi-host builds (a Mac or
# Windows box feeding a separate release host) use the three scripts directly --
# see publish_connector_artifact.sh for the CRYOSTACK_RELEASE_* environment.
#
#   bash build_deploy_connector.sh                 # build this host + release
#   CRYOSTACK_SKIP_BUILD=1 bash build_deploy_connector.sh   # register+release existing dist/packages
#
# The served directory is a deployment target only; the canonical store
# (<store>/) is the source of truth for what is publicly available.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

SKIP_BUILD="${CRYOSTACK_SKIP_BUILD:-0}"
STORE="${CRYOSTACK_CONNECTOR_STORE:-$HOME/.cryostack/connector-artifacts}"

if [[ "$SKIP_BUILD" != "1" ]]; then
  echo "[deploy] 1/3 native build for this host ..."
  bash "$REPO_ROOT/build_connector.sh"
else
  echo "[deploy] 1/3 CRYOSTACK_SKIP_BUILD=1 -> registering existing dist/packages/ artifact"
fi

echo "[deploy] 2/3 register into the canonical store ($STORE) ..."
bash "$REPO_ROOT/publish_connector_artifact.sh"

echo "[deploy] 3/3 generate + promote the public release ..."
bash "$REPO_ROOT/release_connector.sh"
