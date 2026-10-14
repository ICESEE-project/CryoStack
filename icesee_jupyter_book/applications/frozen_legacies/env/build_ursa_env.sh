#!/usr/bin/env bash
# Build the separate Python environment Frozen Legacies runs URSA with.
#
#   build_ursa_env.sh [PREFIX]        (default: ~/.cryostack-envs/ursa)
#
# The gateway's own environment is never modified: URSA runs as a
# subprocess with CRYOSTACK_FROZEN_LEGACIES_URSA_PYTHON=<PREFIX>/bin/python.
# The interpreter comes from conda-forge; packages are the exact set in
# ursa-requirements.lock, installed without dependency resolution. The
# script ends with the same health check the gateway runs.
set -euo pipefail

PREFIX="${1:-$HOME/.cryostack-envs/ursa}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$(dirname "$HERE")"
REPO="$(cd "$APP/../../.." && pwd)"
URSA_ROOT="${CRYOSTACK_FROZEN_LEGACIES_URSA_ROOT:-$REPO/external/FrozenLegacies/Frozen Legacy Tools/Unsupervised Retrieval of Signal for A-scopes (U.R.S.A.)}"
CONDA="${CONDA_EXE:-conda}"
PYTHON_VERSION="3.11"

if [ -e "$PREFIX" ]; then
  echo "$PREFIX already exists; remove it first to rebuild." >&2
  exit 1
fi
if [ ! -f "$URSA_ROOT/ascope_processor.py" ]; then
  echo "URSA sources not found (initialize the external/FrozenLegacies submodule)." >&2
  exit 1
fi

"$CONDA" create -y -q -p "$PREFIX" --override-channels -c conda-forge "python=$PYTHON_VERSION" pip

# the service user's ~/.local packages must not satisfy or shadow anything
export PYTHONNOUSERSITE=1
"$PREFIX/bin/python" -m pip install --no-cache-dir --no-deps -r "$HERE/ursa-requirements.lock"
"$PREFIX/bin/python" -m pip check

cd "$(mktemp -d)"
env -i PATH=/usr/bin:/bin HOME="$HOME" MPLBACKEND=Agg PYTHONNOUSERSITE=1 \
  "$PREFIX/bin/python" "$APP/pickers/ursa_runner.py" --check --ursa-root "$URSA_ROOT"

echo
echo "URSA environment ready. Gateway setting:"
echo "  CRYOSTACK_FROZEN_LEGACIES_URSA_PYTHON=$PREFIX/bin/python"
