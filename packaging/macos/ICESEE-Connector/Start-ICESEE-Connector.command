#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

SESSION="$1"

if [[ -z "$SESSION" ]]; then
  echo "No session provided."
  echo "Opening connector using latest ICESEE session..."
  ./icesee_hpc_connector/icesee-connect
else
  ./icesee_hpc_connector/icesee-connect --session "$SESSION"
fi

echo
echo "Connector stopped. You can close this window."
read -n 1 -s -r -p "Press any key to close..."
