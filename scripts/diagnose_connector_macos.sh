#!/usr/bin/env bash
# =============================================================================
# Diagnose a hung / unresponsive CryoStack Connector on macOS -- specifically
# the case where the copy in /Applications misbehaves while the DMG / other
# copy works. Pairing/relay is NOT the subject here.
#
#   bash scripts/diagnose_connector_macos.sh
# =============================================================================
set -u

APP="/Applications/CryoStack Connector.app"
LOCK="$HOME/.cryostack/connector.lock"
LOG="$HOME/icesee_connector.log"

sec() { printf '\n==== %s ====\n' "$1"; }

sec "running connector processes"
pgrep -fl 'CryoStack Connector' || echo "(none)"

sec "single-instance lock"
if [ -f "$LOCK" ]; then
  ls -l "$LOCK"; echo "pid in lock: $(cat "$LOCK" 2>/dev/null)"
  if command -v lsof >/dev/null 2>&1; then lsof "$LOCK" 2>/dev/null || echo "(lock not held)"; fi
else
  echo "(no lock file at $LOCK)"
fi

sec "quarantine / translocation xattrs on the installed app"
if [ -d "$APP" ]; then
  xattr -l "$APP" 2>/dev/null || echo "(no xattrs)"
  echo "-- to clear quarantine (stops translocation):"
  echo "   xattr -dr com.apple.quarantine \"$APP\""
else
  echo "(not installed at $APP)"
fi

sec "code signature"
if [ -d "$APP" ]; then
  codesign -dv --verbose=2 "$APP" 2>&1 || echo "(unsigned)"
fi

sec "Gatekeeper assessment (spctl)"
if [ -d "$APP" ]; then
  spctl -a -vvv -t exec "$APP" 2>&1 || true
fi

sec "is the app currently running from a translocated path?"
P="$(pgrep -f 'CryoStack Connector' | head -1)"
if [ -n "${P:-}" ]; then
  ps -o command= -p "$P"
  case "$(ps -o command= -p "$P")" in
    *AppTranslocation*) echo ">>> TRANSLOCATED: clear the quarantine xattr and relaunch." ;;
    *) echo "(not translocated)" ;;
  esac
fi

sec "last lifecycle events"
[ -f "$LOG" ] && grep '\[lifecycle\]' "$LOG" | tail -15 || echo "(no log)"

sec "if it is hung, capture the main-thread stack"
if [ -n "${P:-}" ]; then
  echo "sample $P 5 -file /tmp/cryostack-connector-sample.txt"
  echo "then inspect /tmp/cryostack-connector-sample.txt for what thread 0 is blocked on"
fi
