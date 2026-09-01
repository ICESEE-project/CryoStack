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
# anonymous session-creation spam is rejected. The GUI/Voila kernels and the
# relay must see the same value, so it is exported here before either starts.
# Persisted once to ~/.cryostack/relay_control_token (mode 0600).
# ------------------------------------------------------------
if [ -z "${CRYOSTACK_RELAY_CONTROL_TOKEN:-}" ]; then
    CRYOSTACK_RELAY_CONTROL_TOKEN="$(
        python3 -m icesee_jupyter_book.core.connector_relay_auth ensure
    )"
    export CRYOSTACK_RELAY_CONTROL_TOKEN
fi


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


# ============================================================
# GUI lifecycle
# ============================================================

stop_gui() {

    section \
        "Stopping CryoStack GUI runtime..."

    pkill -f \
        "icesee_app.py" \
        || true

    pkill -f \
        "python.*-m voila" \
        || true


    sleep 2


    echo
    echo "[CryoStack] Remaining GUI processes:"

    gui_processes

}


start_gui() {

    section \
        "Starting CryoStack GUI services..."

    nohup bash \
        "${REPO_ROOT}/bin/start_icesee_services.sh" \
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

    nohup python \
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