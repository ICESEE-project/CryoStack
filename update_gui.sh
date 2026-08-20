#!/usr/bin/env bash

# ============================================================
# CryoStack Selective Application Update
#
# Usage:
#
#   ./update_gui.sh frozen-legacies
#   ./update_gui.sh livist
#   ./update_gui.sh livist-docs
#   ./update_gui.sh cryostack-book
#
# Application build, restart scope, dependencies, and health
# targets are resolved from deployment/applications.yaml.
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
REGISTRY="${DEPLOYMENT_DIR}/applications.yaml"


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


usage() {

    echo
    echo "Usage:"
    echo "  $0 <application>"
    echo
    echo "Examples:"
    echo "  $0 frozen-legacies"
    echo "  $0 livist"
    echo "  $0 livist-docs"
    echo "  $0 cryostack-book"
    echo

}


recover_runtime() {

    local scope="$1"

    echo
    echo "[CryoStack] Attempting runtime recovery..."

    case "${scope}" in

        none)
            ;;

        gui)
            "${SERVICES}" start-gui \
                || true
            ;;

        connector)
            "${SERVICES}" start-connector \
                || true
            ;;

        all)
            "${SERVICES}" start \
                || true
            ;;

        *)
            echo \
                "[CryoStack][WARN] Unknown recovery scope: ${scope}"
            ;;

    esac

}


stop_runtime_scope() {

    local scope="$1"

    case "${scope}" in

        none)

            echo \
                "[CryoStack] No runtime restart required."
            ;;


        gui)

            echo \
                "[CryoStack] Stopping GUI runtime only."

            "${SERVICES}" stop-gui
            ;;


        connector)

            echo \
                "[CryoStack] Stopping connector relay only."

            "${SERVICES}" stop-connector
            ;;


        all)

            echo \
                "[CryoStack] Stopping all CryoStack runtime services."

            "${SERVICES}" stop
            ;;


        *)

            echo
            echo \
                "[CryoStack][ERROR] Invalid restart scope: ${scope}"

            exit 2
            ;;

    esac

}


start_runtime_scope() {

    local scope="$1"

    case "${scope}" in

        none)
            ;;


        gui)

            "${SERVICES}" start-gui
            ;;


        connector)

            "${SERVICES}" start-connector
            ;;


        all)

            "${SERVICES}" start
            ;;


        *)

            echo
            echo \
                "[CryoStack][ERROR] Invalid restart scope: ${scope}"

            exit 2
            ;;

    esac

}


# ============================================================
# Arguments
# ============================================================

TARGET="${1:-}"


if [ -z "${TARGET}" ]; then

    usage

    exit 2

fi


# ============================================================
# Validate deployment tooling
# ============================================================

for path in \
    "${PREFLIGHT}" \
    "${BUILDER}" \
    "${SERVICES}" \
    "${HEALTH_CHECK}" \
    "${REGISTRY}"
do

    if [ ! -e "${path}" ]; then

        echo
        echo "[CryoStack][ERROR] Missing deployment component:"
        echo "  ${path}"

        exit 1

    fi

done


section \
    "CryoStack selective update"

echo "Application:"
echo "  ${TARGET}"

echo
echo "Repository:"
echo "  ${REPO_ROOT}"


# ============================================================
# 1. Preflight
# ============================================================

section \
    "1/4 Preflight"


python \
    "${PREFLIGHT}" \
    --application "${TARGET}"


# ============================================================
# 2. Resolve deployment policy
# ============================================================

section \
    "2/4 Resolving deployment policy"


POLICY_JSON="$(
    python \
        "${BUILDER}" \
        policy \
        "${TARGET}"
)"


RESTART_SCOPE="$(
    python -c '
import json
import sys

payload = json.load(sys.stdin)

print(
    payload.get(
        "restart_scope",
        "none",
    )
)
' <<< "${POLICY_JSON}"
)"


HEALTH_TARGET="$(
    python -c '
import json
import sys

payload = json.load(sys.stdin)

print(
    payload.get(
        "health_target"
    )
    or ""
)
' <<< "${POLICY_JSON}"
)"


DEPENDENCIES="$(
    python -c '
import json
import sys

payload = json.load(sys.stdin)

print(
    ", ".join(
        payload.get(
            "applications",
            [],
        )
    )
)
' <<< "${POLICY_JSON}"
)"


echo "Resolved build graph:"
echo "  ${DEPENDENCIES:-${TARGET}}"

echo
echo "Restart scope:"
echo "  ${RESTART_SCOPE}"

echo
echo "Health target:"
echo "  ${HEALTH_TARGET:-none}"


# ============================================================
# 3. Build
# ============================================================

section \
    "3/4 Building ${TARGET}"


stop_runtime_scope \
    "${RESTART_SCOPE}"


if ! python \
    "${BUILDER}" \
    build \
    "${TARGET}"
then

    echo
    echo "[CryoStack][ERROR] Build failed:"
    echo "  ${TARGET}"

    recover_runtime \
        "${RESTART_SCOPE}"

    exit 1

fi


if ! start_runtime_scope \
    "${RESTART_SCOPE}"
then

    echo
    echo "[CryoStack][ERROR] Runtime startup failed."

    echo "Restart scope:"
    echo "  ${RESTART_SCOPE}"

    echo
    echo "Inspect:"
    echo "  ${REPO_ROOT}/icesee.log"
    echo "  ${REPO_ROOT}/relay.log"

    exit 1

fi


# ============================================================
# 4. Health check
# ============================================================

section \
    "4/4 Health check"


if [ -n "${HEALTH_TARGET}" ]; then

    python \
        "${HEALTH_CHECK}" \
        --application "${HEALTH_TARGET}" \
        --wait 45

else

    echo \
        "[CryoStack] No application-specific health target configured."

    echo \
        "[CryoStack] Running full platform health check."

    python \
        "${HEALTH_CHECK}" \
        --wait 60

fi


# ============================================================
# Success
# ============================================================

section \
    "CryoStack application update complete"


echo "Application:"
echo "  ${TARGET}"

echo
echo "Build graph:"
echo "  ${DEPENDENCIES:-${TARGET}}"

echo
echo "Runtime restart scope:"
echo "  ${RESTART_SCOPE}"


if [ "${RESTART_SCOPE}" = "none" ]; then

    echo
    echo \
        "Other CryoStack applications remained online."

fi