#!/usr/bin/env bash
# Sourced with the installer and workflow locks held. Never infer project ownership.
[[ "$fresh" == yes ]] || return 0
if [[ "$autostart" == keep ]]; then
    if systemctl --user is-enabled --quiet "$service"; then autostart=yes; else autostart=no; fi
fi
fresh_reset() {
    "$python_bin" -I -c \
        'import sys; sys.path.insert(0, sys.argv.pop(1)); from countersign.deployment.fresh import main; main()' \
        "$source_dir" "$1" "$source_dir" "$initial_settings"
}
# Validate the complete deletion set before stopping or deleting anything.
fresh_reset check
executor_reset=no
if [[ -e /etc/systemd/system/countersign-executor.service || -d /opt/countersign-executor ]]; then
    executor_reset=yes
    sudo -v
    sudo bash "$source_dir/deploy/reset-executor.sh"
fi
systemctl --user stop "$service" 2>/dev/null || {
    if systemctl --user is-active --quiet "$service"; then
        echo 'Cannot stop service; reset aborted' >&2
        exit 1
    fi
}
systemctl --user disable "$service" 2>/dev/null || true
fresh_reset remove
systemctl --user daemon-reload
systemctl --user reset-failed "$service" 2>/dev/null || true
mkdir -p "$app_dir/releases" "$config_dir" "$state_dir/runs"
agent_mode=bundled
