#!/usr/bin/env bash

# ============================================================
# CryoStack Runtime Service Manager
#
# Usage:
#
#   deployment/services.sh start
#   deployment/services.sh stop
#   deployment/services.sh restart
#   deployment/services.sh status
#
# Scoped operations:
#
#   deployment/services.sh start-gui
#   deployment/services.sh stop-gui
#   deployment/services.sh restart-gui
#
#   deployment/services.sh start-connector
#   deployment/services.sh stop-connector
#   deployment/services.sh restart-connector
#
# This script manages runtime services only.
# It does NOT build CryoStack applications.
# ============================================================

set -Eeuo pipefail


SCRIPT_DIR="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
    pwd
)"

REPO_ROOT="$(
    cd -- "${SCRIPT_DIR}/.."
    pwd
)"


GUI_LOG="${REPO_ROOT}/icesee.log"
RELAY_LOG="${REPO_ROOT}/relay.log"

GUI_PORT=8080
RELAY_PORT=8899


cd "${REPO_ROOT}"


# ------------------------------------------------------------
# Shared connector-relay deployment token.
#
# Gates relay session creation so a session's owner_user_id is trustworthy and
# anonymous session-creation spam is rejected. The gateway and the relay must
# see the same value, so it is exported here before either starts. Voila
# kernels never receive it: the gateway forwards each user only a grant derived
# from it that can create that user's own sessions.
# Persisted once to ~/.cryostack/relay_control_token (mode 0600).
# ------------------------------------------------------------
if [ -z "${CRYOSTACK_RELAY_CONTROL_TOKEN:-}" ]; then
    CRYOSTACK_RELAY_CONTROL_TOKEN="$(
        python3 -m icesee_jupyter_book.core.connector_relay_auth ensure
    )"
    export CRYOSTACK_RELAY_CONTROL_TOKEN
fi


# ------------------------------------------------------------
# CryoStack Agent interaction mode (Basic | Advanced | Agent).
#
# The already-implemented "Agent" mode in the IceSheets gateway is opt-in via
# CRYOSTACK_AGENT_PANEL and is off unless this is set. This deployment exposes
# it, so default the flag on here (the same place the GUI/Voila kernels pick up
# their shared environment). Still overridable -- run with
# CRYOSTACK_AGENT_PANEL=0 to hide the mode again. This changes no code path:
# Agent mode stays capped at PLAN with no submit backend wired.
# ------------------------------------------------------------
export CRYOSTACK_AGENT_PANEL="${CRYOSTACK_AGENT_PANEL:-1}"

export AWS_PROFILE="${AWS_PROFILE:-cryostack-service}"

export CRYOSTACK_AWS_PRINCIPAL_ARN="${CRYOSTACK_AWS_PRINCIPAL_ARN:-arn:aws:iam::713938953301:user/cryostack-service}"

export CRYOSTACK_CF_TEMPLATE_URL="${CRYOSTACK_CF_TEMPLATE_URL:-https://cryostack-cloudformation-713938953301.s3.us-east-2.amazonaws.com/cryostack-execution-role.json}"

# Frozen Legacies automatic picker. Keep this explicit in production so a
# launcher or inherited shell cannot silently select the historical backend.
# URSA remains available as the rollback value.
export CRYOSTACK_FROZEN_LEGACIES_AUTOMATIC_PICKER="${CRYOSTACK_FROZEN_LEGACIES_AUTOMATIC_PICKER:-lyra}"
export CRYOSTACK_FROZEN_LEGACIES_URSA_CONCURRENCY="${CRYOSTACK_FROZEN_LEGACIES_URSA_CONCURRENCY:-1}"

# Read-only Georgia Tech CEDAR research storage approved for Frozen Legacies
# catalog sources. Source registrations may select this mount or a child path;
# the gateway never writes to it.
# Scratch is an explicitly labelled, maintainer-only transitional source for
# verified A-/Z-scope intake. It is never an authoritative publication target;
# CEDAR promotion must re-index the same source from durable storage.
export CRYOSTACK_FROZEN_LEGACIES_STORAGE_ROOTS="${CRYOSTACK_FROZEN_LEGACIES_STORAGE_ROOTS:-/projects/cos-lab-nuiaq:/home/bkyanjo3/cryostack-data/datasets:/scratch/cryostack-development/incoming}"

# Verified SPRI navigation is published as an immutable, versioned data release
# under the durable application data root.  Keep these defaults in the runtime
# launcher so an operator restart cannot silently remove the map coverage.
export CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_ROOT="${CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_ROOT:-/home/bkyanjo3/cryostack-data/datasets/spri/navigation-current}"
export CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_FLIGHTS="${CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_FLIGHTS:-125,126,127,128,137,138,139,141,143,149}"
export CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_DATASET="${CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_DATASET:-frozen-legacies-spri-navigation}"
export CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_TITLE="${CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_TITLE:-SPRI archival radar navigation}"

# Optional, independently versioned RIGGS scientific context. A manifest may
# explicitly carry citation_pending=true; the API and UI then keep every point
# provisional and publication-ineligible until complete provenance is supplied.
export CRYOSTACK_FROZEN_LEGACIES_RIGGS_CSV="${CRYOSTACK_FROZEN_LEGACIES_RIGGS_CSV:-/home/bkyanjo3/cryostack-data/datasets/riggs/current/riggs_stations.csv}"
export CRYOSTACK_FROZEN_LEGACIES_RIGGS_MANIFEST="${CRYOSTACK_FROZEN_LEGACIES_RIGGS_MANIFEST:-/home/bkyanjo3/cryostack-data/datasets/riggs/current/manifest.json}"

# All authoritative state lives outside the source checkout. The gateway's
# storage-layout gate verifies the marked volume before accepting traffic.
export CRYOSTACK_DATA_ROOT="${CRYOSTACK_DATA_ROOT:-/home/bkyanjo3/cryostack-data}"
export CRYOSTACK_REQUIRE_DURABLE_STORAGE="${CRYOSTACK_REQUIRE_DURABLE_STORAGE:-1}"


# ============================================================
# Helpers
# ============================================================

section() {

    echo
    echo "=================================================="
    echo "$1"
    echo "=================================================="

}


processes() {

    ps -ef \
        | grep -E \
          "icesee_app.py|voila|connector_relay_server|uvicorn" \
        | grep -v grep \
        || true

}


gui_processes() {

    ps -ef \
        | grep -E \
          "icesee_app.py|voila" \
        | grep -v grep \
        || true

}


connector_processes() {

    ps -ef \
        | grep -E \
          "connector_relay_server|uvicorn" \
        | grep -v grep \
        || true

}


terminate_matching() {
    pattern="$1"
    pids="$(pgrep -f -- "${pattern}" 2>/dev/null || true)"
    [ -z "${pids}" ] && return 0
    # A remote shell's command line can contain the same absolute path passed
    # as the search pattern.  Never terminate this manager or any of its
    # ancestors while selecting the actual service processes.
    protected=" $$"
    ancestor="${PPID}"
    while [ -n "${ancestor}" ] && [ "${ancestor}" -gt 1 ] 2>/dev/null; do
        protected="${protected} ${ancestor}"
        ancestor="$(ps -o ppid= -p "${ancestor}" 2>/dev/null | tr -d ' ' || true)"
    done
    targets=""
    for pid in ${pids}; do
        case " ${protected} " in
            *" ${pid} "*) ;;
            *) targets="${targets} ${pid}" ;;
        esac
    done
    [ -z "${targets}" ] && return 0
    kill ${targets} 2>/dev/null || true
    attempts=0
    while [ "${attempts}" -lt 20 ]; do
        alive=""
        for pid in ${targets}; do
            kill -0 "${pid}" 2>/dev/null && alive="${alive} ${pid}"
        done
        [ -z "${alive}" ] && return 0
        sleep 0.25
        attempts=$((attempts + 1))
    done
    # A wedged gateway must not coexist with its replacement.
    kill -KILL ${alive} 2>/dev/null || true
}


# ============================================================
# GUI lifecycle
# ============================================================

stop_gui() {

    section \
        "Stopping CryoStack GUI runtime..."

    terminate_matching "${REPO_ROOT}/bin/icesee_app.py"
    terminate_matching "python.*-m voila"


    sleep 2


    echo
    echo "[CryoStack] Remaining GUI processes:"

    gui_processes

}


start_gui() {

    section \
        "Starting CryoStack GUI services..."

    # Detach the gateway from the invoking terminal as well as ignoring HUP.
    # Remote deployment shells may close immediately after this command; a
    # separate session prevents that teardown from killing only the gateway
    # while leaving its Voilà children orphaned.
    nohup setsid bash \
        "${REPO_ROOT}/bin/start_icesee_services.sh" \
        < /dev/null \
        > "${GUI_LOG}" \
        2>&1 &

    GUI_PID=$!


    sleep 5


    if ! kill -0 \
        "${GUI_PID}" \
        2>/dev/null
    then

        echo
        echo \
            "[CryoStack][ERROR] GUI service failed to start."

        echo \
            "Inspect: ${GUI_LOG}"

        tail -n 50 \
            "${GUI_LOG}" \
            || true

        return 1

    fi


    echo
    echo \
        "[CryoStack] GUI launcher PID: ${GUI_PID}"

}


restart_gui() {

    stop_gui

    start_gui

}


# ============================================================
# Connector lifecycle
# ============================================================

stop_connector() {

    section \
        "Stopping CryoStack connector relay..."

    pkill -f \
        "connector_relay_server" \
        || true

    pkill -f \
        "python.*-m uvicorn" \
        || true


    sleep 2


    echo
    echo "[CryoStack] Remaining connector processes:"

    connector_processes

}


start_connector() {

    section \
        "Starting connector relay server..."

    nohup setsid python \
        -m uvicorn \
        icesee_jupyter_book.core.connector_relay_server:app \
        --host 127.0.0.1 \
        --port "${RELAY_PORT}" \
        > "${RELAY_LOG}" \
        2>&1 &

    RELAY_PID=$!


    sleep 3


    if ! kill -0 \
        "${RELAY_PID}" \
        2>/dev/null
    then

        echo
        echo \
            "[CryoStack][ERROR] Connector relay failed to start."

        echo \
            "Inspect: ${RELAY_LOG}"

        tail -n 50 \
            "${RELAY_LOG}" \
            || true

        return 1

    fi


    echo
    echo \
        "[CryoStack] Relay PID: ${RELAY_PID}"

}


restart_connector() {

    stop_connector

    start_connector

}


# ============================================================
# Full runtime lifecycle
# ============================================================

stop_services() {

    section \
        "Stopping CryoStack runtime services..."

    # Stop connector first.
    stop_connector

    # Then stop GUI / Voilà services.
    stop_gui


    echo
    echo "[CryoStack] Remaining matching processes:"

    processes

}


start_services() {

    # Preserve the existing startup order:
    #
    # 1. GUI
    # 2. Connector relay

    start_gui

    start_connector


    section \
        "CryoStack runtime services started"

    echo

    echo "Applications:"
    echo "  CryoStack:        http://127.0.0.1:8080/"
    echo "  CryoLauncher:     http://127.0.0.1:8080/icesheets/"
    echo "  ICESEE:           http://127.0.0.1:8080/icesee-gui/"
    echo "  LIVIST:           http://127.0.0.1:8080/livist/"
    echo "  LIVIST docs:      http://127.0.0.1:8080/livist/docs/"
    echo "  Frozen Legacies:  http://127.0.0.1:8080/frozen-legacies/"

    echo

    echo "Logs:"
    echo "  tail -f ${GUI_LOG}"
    echo "  tail -f ${RELAY_LOG}"

    echo

    echo "Ports:"
    echo "  GUI:              ${GUI_PORT}"
    echo "  Connector:        ${RELAY_PORT}"

}


restart_services() {

    stop_services

    start_services

}


# ============================================================
# Status
# ============================================================

status_services() {

    section \
        "CryoStack runtime status"

    echo

    echo "GUI processes:"
    gui_processes

    echo

    echo "Connector processes:"
    connector_processes

    echo

    echo "Expected ports:"

    printf \
        "%-18s %s\n" \
        "GUI:" \
        "${GUI_PORT}"

    printf \
        "%-18s %s\n" \
        "Connector:" \
        "${RELAY_PORT}"

}


# ============================================================
# Command dispatcher
# ============================================================

ACTION="${1:-status}"


case "${ACTION}" in

    # --------------------------------------------------------
    # Full runtime
    # --------------------------------------------------------

    start)

        start_services
        ;;


    stop)

        stop_services
        ;;


    restart)

        restart_services
        ;;


    # --------------------------------------------------------
    # GUI only
    # --------------------------------------------------------

    start-gui)

        start_gui
        ;;


    stop-gui)

        stop_gui
        ;;


    restart-gui)

        restart_gui
        ;;


    # --------------------------------------------------------
    # Connector only
    # --------------------------------------------------------

    start-connector)

        start_connector
        ;;


    stop-connector)

        stop_connector
        ;;


    restart-connector)

        restart_connector
        ;;


    # --------------------------------------------------------
    # Status
    # --------------------------------------------------------

    status)

        status_services
        ;;


    *)

        echo
        echo \
            "[CryoStack][ERROR] Unknown service action: ${ACTION}"

        echo

        echo "Usage:"
        echo "  $0 start"
        echo "  $0 stop"
        echo "  $0 restart"
        echo "  $0 status"
        echo
        echo "Scoped GUI operations:"
        echo "  $0 start-gui"
        echo "  $0 stop-gui"
        echo "  $0 restart-gui"
        echo
        echo "Scoped connector operations:"
        echo "  $0 start-connector"
        echo "  $0 stop-connector"
        echo "  $0 restart-connector"

        exit 2
        ;;

esac
