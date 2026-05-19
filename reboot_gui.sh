#!/usr/bin/env bash

# ============================================================
# ICESEE GUI + Connector Launcher
# ============================================================

set -e

cd ~/ICESEE-GHUB

echo "=================================================="
echo "Stopping existing ICESEE services..."
echo "=================================================="

pkill -f connector_relay_server || true
pkill -f icesee_app.py || true
pkill -f voila || true
pkill -f uvicorn || true

sleep 2

echo "=================================================="
echo "Building Jupyter Book..."
echo "=================================================="

jupyter-book build icesee_jupyter_book

sleep 5

echo
echo "=================================================="
echo "Starting ICESEE GUI services..."
echo "=================================================="

nohup bash bin/start_icesee_services.sh \
    > icesee.log 2>&1 &

GUI_PID=$!

sleep 5

echo
echo "=================================================="
echo "Starting Connector Relay Server..."
echo "=================================================="

nohup python -m uvicorn icesee_jupyter_book.core.connector_relay_server:app \
    --host 127.0.0.1 \
    --port 8899 \
    > relay.log 2>&1 &

RELAY_PID=$!

sleep 3

echo
echo "=================================================="
echo "ICESEE Services Started"
echo "=================================================="

echo "GUI PID:        $GUI_PID"
echo "Relay PID:      $RELAY_PID"

echo
echo "Logs:"
echo "  tail -f ~/ICESEE-GHUB/icesee.log"
echo "  tail -f ~/ICESEE-GHUB/relay.log"

echo
echo "Ports:"
echo "  GUI:           8080"
echo "  Connector:     8899"

echo
echo "Check processes:"
ps -ef | grep -E "voila|connector_relay_server" | grep -v grep
