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
# Immutable supplied measurements: all collections use one verified CEDAR release.
export CRYOSTACK_FROZEN_LEGACIES_RELEASE_ROOT="${CRYOSTACK_FROZEN_LEGACIES_RELEASE_ROOT:-/srv/cryostack/workspace/datasets/frozen-legacies/measurements/releases}"
export CRYOSTACK_FROZEN_LEGACIES_RELEASE_ID="${CRYOSTACK_FROZEN_LEGACIES_RELEASE_ID:-404a7aca22c9e4ea9db720ec574e28bbdd8c9571d3f5504101b0f597ea31fc03}"

export CRYOSTACK_FROZEN_LEGACIES_AUTOMATIC_PICKER="${CRYOSTACK_FROZEN_LEGACIES_AUTOMATIC_PICKER:-lyra}"
export CRYOSTACK_FROZEN_LEGACIES_URSA_CONCURRENCY="${CRYOSTACK_FROZEN_LEGACIES_URSA_CONCURRENCY:-1}"

# Georgia Tech CEDAR scientific storage is authoritative for large Frozen
# Legacies datasets. The local durable root and scratch remain approved during
# the migration rollback window; scratch is never a publication target.
export CRYOSTACK_FROZEN_LEGACIES_STORAGE_ROOTS="${CRYOSTACK_FROZEN_LEGACIES_STORAGE_ROOTS:-/srv/cryostack/workspace/datasets:/home/bkyanjo3/cryostack-data/datasets:/scratch/cryostack-development/incoming}"

# Browser uploads, resumable session records and the shared writer lock are
# mutable state. Keep them on the marked local XFS durable volume: the active
# SMB dataset share failed lock acceptance and is restricted to immutable
# releases. Moving an existing intake requires a separately reviewed migration.
export CRYOSTACK_FROZEN_LEGACIES_INTAKE_ROOT="${CRYOSTACK_FROZEN_LEGACIES_INTAKE_ROOT:-/home/bkyanjo3/cryostack-data/datasets/frozen-legacies/intakes}"

# Verified SPRI navigation is published as an immutable, versioned data release
# under the durable application data root.  Keep these defaults in the runtime
# launcher so an operator restart cannot silently remove the map coverage.
export CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_ROOT="${CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_ROOT:-/srv/cryostack/workspace/datasets/frozen-legacies/spri/navigation/releases/nav-177c92df4cc0f690}"
export CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_FLIGHTS="${CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_FLIGHTS:-125,126,127,128,137,138,139,141,143,149}"
export CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_DATASET="${CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_DATASET:-frozen-legacies-spri-navigation}"
export CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_TITLE="${CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_TITLE:-SPRI archival radar navigation}"

# Optional, independently versioned RIGGS scientific context. A manifest may
# explicitly carry citation_pending=true; the API and UI then keep every point
# provisional and publication-ineligible until complete provenance is supplied.
export CRYOSTACK_FROZEN_LEGACIES_RIGGS_CSV="${CRYOSTACK_FROZEN_LEGACIES_RIGGS_CSV:-/srv/cryostack/workspace/datasets/frozen-legacies/riggs/releases/riggs-e83879057daf36a0/riggs_stations.csv}"
export CRYOSTACK_FROZEN_LEGACIES_RIGGS_MANIFEST="${CRYOSTACK_FROZEN_LEGACIES_RIGGS_MANIFEST:-/srv/cryostack/workspace/datasets/frozen-legacies/riggs/releases/riggs-e83879057daf36a0/manifest.json}"

# All authoritative state lives outside the source checkout. The gateway's
# storage-layout gate verifies the marked volume before accepting traffic.
export CRYOSTACK_DATA_ROOT="${CRYOSTACK_DATA_ROOT:-/home/bkyanjo3/cryostack-data}"
export CRYOSTACK_REQUIRE_DURABLE_STORAGE="${CRYOSTACK_REQUIRE_DURABLE_STORAGE:-1}"

# New accounts wait for administrator approval (Control Center ->
# Registrations). Existing accounts were baselined as approved with
# deployment/auth_db_migrate.py approval-baseline. Mail stays queued
# (disabled) until a relay is configured; links use the public origin.
export CRYOSTACK_REGISTRATION_APPROVAL="${CRYOSTACK_REGISTRATION_APPROVAL:-1}"
export CRYOSTACK_MAIL_MODE="${CRYOSTACK_MAIL_MODE:-disabled}"
# Owner-only approval pilot; no other Control Center role can decide.
export CRYOSTACK_APPROVAL_OWNER_ONLY="${CRYOSTACK_APPROVAL_OWNER_ONLY:-1}"
export CRYOSTACK_APPROVAL_ADMIN_EMAILS="${CRYOSTACK_APPROVAL_ADMIN_EMAILS:-brian.kyanjo@aims.ac.rw}"
export CRYOSTACK_PUBLIC_BASE_URL="${CRYOSTACK_PUBLIC_BASE_URL:-https://cryostack.eas.gatech.edu}"

# Private provider settings persist independently of this checkout. Only mail
# settings are accepted; JSON values are quoted and never executed as code.
# Keep GT SMTP keys in the JSON when selecting resend/postmark for rollback.
CRYOSTACK_MAIL_CONFIG_FILE="${CRYOSTACK_MAIL_CONFIG_FILE:-${HOME}/.config/cryostack/mail.json}"
case "${1:-}" in
    start|restart|start-gui|restart-gui)
        if [ -e "${CRYOSTACK_MAIL_CONFIG_FILE}" ] || [ -L "${CRYOSTACK_MAIL_CONFIG_FILE}" ]; then
            mail_exports="$(python3 "${REPO_ROOT}/deployment/mail_config.py" "${CRYOSTACK_MAIL_CONFIG_FILE}")"
            eval "${mail_exports}"
            unset mail_exports
        fi
        ;;
esac



# Hosted deployment configuration is private and restricted to the production checkout.
# Paid admission is controlled independently by Control Center.
if [[ "${REPO_ROOT}" == /home/bkyanjo3/CryoLauncher && -r "${CRYOSTACK_DATA_ROOT}/control/pilot713/pilot.json" ]]; then
    export CRYOSTACK_PILOT_CONFIG="${CRYOSTACK_PILOT_CONFIG:-${CRYOSTACK_DATA_ROOT}/control/pilot713/pilot.json}"
    export CRYOSTACK_PILOT_UI_ENABLED="${CRYOSTACK_PILOT_UI_ENABLED:-1}"
    export CRYOSTACK_HOSTED_LICENSE_ENABLED="${CRYOSTACK_HOSTED_LICENSE_ENABLED:-1}"
fi

# Authenticated HTTP downloads for completed owner-scoped result archives.
export CRYOSTACK_STREAM_DOWNLOADS="${CRYOSTACK_STREAM_DOWNLOADS:-1}"

# Service-managed CEDAR bulk workspace; local coordination/credentials remain on XFS.
export CRYOSTACK_WORKSPACE_ROOT="${CRYOSTACK_WORKSPACE_ROOT:-/srv/cryostack/workspace/users/workspaces-20261026}"
export CRYOSTACK_WORKSPACE_STATE_ROOT="${CRYOSTACK_WORKSPACE_STATE_ROOT:-/home/bkyanjo3/cryostack-data/workspace}"
export CRYOSTACK_WORKSPACE_MOUNT="${CRYOSTACK_WORKSPACE_MOUNT:-/srv/cryostack/workspace/users}"
export CRYOSTACK_WORKSPACE_VOLUME_ID="${CRYOSTACK_WORKSPACE_VOLUME_ID:-ea17ef81309e4b3e8c06eea97882b8de}"

# Reviewed native example trees, shared read-only by the model installations.
# Discovery alone never grants access. Preserve an explicit operator override,
# including an empty value (which intentionally disables canonical access).
export CRYOSTACK_CANONICAL_EXAMPLE_ROOTS="${CRYOSTACK_CANONICAL_EXAMPLE_ROOTS-${ISSM_DIR:-${HOME}/ISSM}/examples:${ICEPACK_ROOT:-${HOME}/icepack}/notebooks}"

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
    # Fresh log per start, opened in append mode so it can be emptied while
    # the gateway runs (`: > icesee.log`) without leaving a sparse file.
    : > "${GUI_LOG}"
    nohup setsid bash \
        "${REPO_ROOT}/bin/start_icesee_services.sh" \
        < /dev/null \
        >> "${GUI_LOG}" \
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
    echo "  CryoLauncher:     http://127.0.0.1:8080/cryolauncher/"
    echo "  ICESEE:           http://127.0.0.1:8080/icesee/"
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


# Autostart coordination (deployment/autostart_runbook.md): an explicit
# operator `stop` leaves a marker so the watchdog keeps the runtime down;
# any start clears it. reboot_gui.sh sets CRYOSTACK_ORCHESTRATED=1 because
# its stop is part of a rebuild, not a decision to keep the site down.
RUNTIME_STOPPED_MARKER="${REPO_ROOT}/var/.runtime-stopped"
case "${ACTION}" in
    stop)
        if [ "${CRYOSTACK_ORCHESTRATED:-0}" != "1" ] && [ -d "${REPO_ROOT}/var" ]; then
            date '+%Y-%m-%d %H:%M:%S operator stop' > "${RUNTIME_STOPPED_MARKER}"
            echo "[CryoStack] Watchdog paused until the next start: ${RUNTIME_STOPPED_MARKER}"
        fi
        ;;
    start|restart|start-gui|restart-gui)
        rm -f "${RUNTIME_STOPPED_MARKER}"
        ;;
esac

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
