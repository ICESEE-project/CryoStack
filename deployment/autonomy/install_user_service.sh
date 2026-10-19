#!/usr/bin/env bash
set -euo pipefail

source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
unit_dir="$HOME/.config/systemd/user"
mkdir -p "$unit_dir"
install -m 0644 "$source_dir/cryostack-autonomy-night.service" "$unit_dir/"
install -m 0644 "$source_dir/cryostack-autonomy-night.timer" "$unit_dir/"
chmod 0755 "$source_dir/run_daily.sh"
systemctl --user disable --now cryostack-autonomy.service cryostack-autonomy.timer || true
rm -f "$unit_dir/cryostack-autonomy.service" "$unit_dir/cryostack-autonomy.timer"
systemctl --user daemon-reload
systemctl --user enable cryostack-autonomy-night.timer
systemctl --user start cryostack-autonomy-night.timer
