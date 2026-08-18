#!/usr/bin/env bash

# ============================================================
# CryoStack Full Rebuild + Restart
#
# Lifecycle:
#
#   1. Preflight
#   2. Stop runtime services
#   3. Build dependency graph
#   4. Validate build artifacts
#   5. Start runtime services
#   6. Health check
#
# Usage:
#
#   ./reboot_gui.sh
#
# ============================================================

set -Eeuo pipefail


SCRIPT_DIR="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
    pwd
)"

REPO_ROOT="${SCRIPT_DIR}"

DEPLOYMENT_DIR="${REPO_ROOT}/deployment"

PREFLIGHT="${DEPLOYMENT_DIR}/preflight.py"
BUILDER="${DEPLOYMENT_DIR}/cryostack_build.py"
SERVICES="${DEPLOYMENT_DIR}/services.sh"
HEALTH_CHECK="${DEPLOYMENT_DIR}/health_check.py"


cd "${REPO_ROOT}"


# ============================================================
# Helpers
# ============================================================

section() {

    echo
    echo "=================================================="
    echo "$1"
    echo "=================================================="

}


deployment_failed() {

    local stage="$1"

    echo
    echo "=================================================="
    echo "[CryoStack][ERROR] Deployment failed"
    echo "Stage: ${stage}"
    echo "=================================================="
    echo

}


# ============================================================
# Validate deployment tooling itself
# ============================================================

section \
    "CryoStack full rebuild and restart"

echo "Repository:"
echo "  ${REPO_ROOT}"


for path in \
    "${PREFLIGHT}" \
    "${BUILDER}" \
    "${SERVICES}" \
    "${HEALTH_CHECK}"
do

    if [ ! -e "${path}" ]; then

        echo
        echo "[CryoStack][ERROR] Missing deployment component:"
        echo "  ${path}"

        exit 1

    fi

done


# ============================================================
# 1. PREFLIGHT
#
# Important:
# Services are still running here.
#
# A failed preflight must NOT interrupt the live platform.
# ============================================================

section \
    "1/5 CryoStack deployment preflight"


if ! python \
    "${PREFLIGHT}"
then

    deployment_failed \
        "preflight"

    echo \
        "Existing CryoStack services were left untouched."

    exit 1

fi


# ============================================================
# 2. STOP RUNTIME
# ============================================================

section \
    "2/5 Stopping CryoStack runtime"


if ! "${SERVICES}" stop
then

    deployment_failed \
        "service shutdown"

    exit 1

fi


# ============================================================
# 3. BUILD
#
# cryostack_build.py handles:
#
#   - dependency ordering
#   - build commands
#   - clean rules
#   - requirement checks
#   - artifact validation
#
# ============================================================

section \
    "3/5 Building CryoStack applications"


if ! python \
    "${BUILDER}" \
    build \
    all
then

    deployment_failed \
        "application build"

    echo
    echo "[CryoStack] Build failed after services were stopped."
    echo "[CryoStack] Attempting to restore the runtime..."

    if "${SERVICES}" start; then

        echo
        echo "[CryoStack] Runtime restart attempted successfully."

        python \
            "${HEALTH_CHECK}" \
            --wait 60 \
            || true

    else

        echo
        echo "[CryoStack][ERROR] Runtime recovery failed."
        echo
        echo "Inspect:"
        echo "  ${REPO_ROOT}/icesee.log"
        echo "  ${REPO_ROOT}/relay.log"

    fi

    exit 1

fi


# ============================================================
# 4. START RUNTIME
# ============================================================

section \
    "4/5 Starting CryoStack runtime"


if ! "${SERVICES}" start
then

    deployment_failed \
        "service startup"

    echo
    echo "Inspect:"
    echo "  ${REPO_ROOT}/icesee.log"
    echo "  ${REPO_ROOT}/relay.log"

    exit 1

fi


# ============================================================
# 5. HEALTH CHECK
# ============================================================

section \
    "5/5 CryoStack health check"


if ! python \
    "${HEALTH_CHECK}" \
    --wait 90
then

    deployment_failed \
        "health check"

    echo
    echo "[CryoStack] Runtime processes started,"
    echo "but one or more application routes are unhealthy."
    echo
    echo "Inspect:"
    echo "  ${REPO_ROOT}/icesee.log"
    echo "  ${REPO_ROOT}/relay.log"

    echo

    "${SERVICES}" status \
        || true

    exit 1

fi


# ============================================================
# Success
# ============================================================

section \
    "CryoStack deployment complete"


echo "Applications:"
echo "  CryoStack:        http://127.0.0.1:8080/"
echo "  CryoLauncher:     http://127.0.0.1:8080/icesheets/"
echo "  ICESEE:           http://127.0.0.1:8080/icesee-gui/"
echo "  LIVIST:           http://127.0.0.1:8080/livist/"
echo "  LIVIST docs:      http://127.0.0.1:8080/livist/docs/"
echo "  Frozen Legacies:  http://127.0.0.1:8080/frozen-legacies/"

echo

echo "Logs:"
echo "  tail -f ${REPO_ROOT}/icesee.log"
echo "  tail -f ${REPO_ROOT}/relay.log"

echo

"${SERVICES}" status