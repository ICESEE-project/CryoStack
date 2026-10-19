#!/usr/bin/env bash
set -euo pipefail

repo="${CRYOSTACK_AUTONOMY_REPO:-$HOME/CryoLauncher}"
data_root="${CRYOSTACK_DATA_ROOT:-$HOME/cryostack-data}"
state_dir="$data_root/autonomy"
prompt="$repo/deployment/autonomy/nightly_prompt.md"
codex_bin="${CRYOSTACK_CODEX_BIN:-$HOME/.local/bin/codex}"

mkdir -p "$state_dir/reports" "$state_dir/logs"
exec 9>"$state_dir/daily.lock"
flock -n 9 || exit 0

export TZ="America/New_York"
hour="$(date +%H)"
minute="$(date +%M)"
now_minutes=$((10#$hour * 60 + 10#$minute))

# The shift crosses midnight. Runs started after midnight belong to the
# preceding evening and end at 03:00 today.
if (( now_minutes >= 1260 )); then
  shift_day="$(date +%F)"
  end_epoch="$(date -d 'tomorrow 03:00' +%s)"
elif (( now_minutes < 180 )); then
  shift_day="$(date -d 'yesterday' +%F)"
  end_epoch="$(date -d 'today 03:00' +%s)"
else
  exit 0
fi

stamp="$state_dir/last-started-night-date"
if [[ -f "$stamp" ]] && [[ "$(<"$stamp")" == "$shift_day" ]]; then
  exit 0
fi
printf '%s\n' "$shift_day" > "$stamp"

report="$state_dir/reports/$shift_day-morning-report.md"
log="$state_dir/logs/$shift_day-night.jsonl"
session_file="$state_dir/$shift_day-session-id"
configured_session_id="${CRYOSTACK_AUTONOMY_SESSION_ID:-}"
if [[ -n "$configured_session_id" ]]; then
  printf '%s\n' "$configured_session_id" > "$session_file"
fi

# Retry temporary failures (including exhausted credits) inside this night's
# window. Resuming the captured session preserves its reasoning and handoff.
attempt=0
status=1
while (( $(date +%s) < end_epoch - 120 )); do
  attempt=$((attempt + 1))
  remaining_seconds=$((end_epoch - $(date +%s)))
  if [[ -s "$session_file" ]]; then
    session_id="$(<"$session_file")"
    timeout "${remaining_seconds}s" "$codex_bin" exec resume \
      --json --output-last-message "$report" "$session_id" \
      "Resume the overnight program from the exact stopping point. Re-read the current diff, work ledger, latest reports, and test evidence; continue safely until the 03:00 Eastern handoff." \
      >> "$log" 2>&1 && status=0 || status=$?
  else
    timeout "${remaining_seconds}s" "$codex_bin" exec \
      --cd "$repo" --approve-for-me --thread-source automation --json \
      --output-last-message "$report" - < "$prompt" >> "$log" 2>&1 \
      && status=0 || status=$?
    session_id="$(sed -n 's/.*"thread_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p;T;q' "$log")"
    [[ -z "$session_id" ]] || printf '%s\n' "$session_id" > "$session_file"
  fi
  (( status == 0 )) && break
  (( $(date +%s) >= end_epoch - 1020 )) && break
  sleep 900
done

if (( status != 0 )); then
  rm -f "$stamp"
  if [[ ! -s "$report" ]]; then
    printf '# CryoStack morning report — %s\n\nThe overnight run stopped before producing a final report. Exit status: `%s`. Review `%s` and resume the saved session before approving deployment.\n' \
      "$shift_day" "$status" "$log" > "$report"
  fi
fi
printf '%s\t%s\t%s\n' "$(date --iso-8601=seconds)" "$status" "$report" \
  > "$state_dir/last-run.tsv"
if command -v notify-send >/dev/null 2>&1; then
  notify-send "CryoStack overnight report" "Morning report ready: $report" || true
fi
exit "$status"
