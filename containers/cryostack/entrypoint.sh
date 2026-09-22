#!/bin/bash
# Foreground entrypoint for the CryoStack platform/gateway image.
#
# Deliberately bypasses deployment/services.sh (which daemonizes with
# nohup + PID files -- fine for the bare-metal VM it was built for, wrong
# inside a container). `exec` replaces this shell with the Python process,
# so bin/icesee_app.py's `web.run_app` event loop becomes PID 1 and receives
# container signals (SIGTERM on `docker stop`) directly.
set -euo pipefail

# shellcheck disable=SC1091
source /opt/conda/etc/profile.d/conda.sh
conda activate cryostack

cd /opt/cryostack
exec python bin/icesee_app.py
