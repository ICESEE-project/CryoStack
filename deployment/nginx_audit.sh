#!/usr/bin/env bash
# =============================================================================
# Read-only nginx audit: every loaded server block, server_name, listen and
# `map` directive, with the file:line it comes from, plus a duplicate check.
#
#   sudo bash deployment/nginx_audit.sh
#
# Use before/after deploy_web.sh to confirm exactly one server block owns
# server_name cryostack.eas.gatech.edu on each listen address.
# =============================================================================
set -euo pipefail

DUMP="$(sudo nginx -T 2>/dev/null)" || {
  echo "nginx -T failed (need root / valid config). Raw test:"
  sudo nginx -t || true
  exit 1
}

section() { printf '\n===== %s =====\n' "$1"; }

section "config files loaded"
printf '%s\n' "$DUMP" | grep -E '^# configuration file ' | sed 's/^# configuration file /  /; s/:$//'

section "map directives (\$connection_upgrade etc.)"
printf '%s\n' "$DUMP" | grep -nE '^\s*map\s+\$' | sed 's/^/  line /' || echo "  (none)"

section "server_name / listen per block"
printf '%s\n' "$DUMP" \
  | grep -nE '^\s*(server\s*\{|listen\s|server_name\s)' \
  | sed 's/^/  /'

section "duplicate server_name check"
DUPES="$(printf '%s\n' "$DUMP" \
  | grep -E '^\s*server_name\s' \
  | sed -E 's/^\s*server_name\s+//; s/;\s*$//' \
  | tr ' ' '\n' | sort | uniq -d)"
if [[ -n "$DUPES" ]]; then
  echo "  DUPLICATE server_name values (nginx will log 'conflicting server name ... ignored'):"
  echo "$DUPES" | sed 's/^/    /'
  echo "  -> exactly one server block per (listen, server_name) pair is expected."
  exit 2
fi
echo "  OK: no server_name appears in more than one block."
