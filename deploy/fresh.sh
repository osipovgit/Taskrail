#!/usr/bin/env bash
# Switch only after validating the incoming release and draining the managed service.
reset_state() {
    run_module taskrail.deployment.fresh "$1" "$source_dir" "$initial_settings" "${reset_options[@]}"
}
reset_options=()
executor_reset=no
service_was_active=no
if [[ "$fresh" == yes ]]; then
    reset_options+=(--incoming-settings "$staging/config/settings.json")
fi
if [[ "$force_update" == yes ]]; then
    reset_options+=(--keep-config "$staging/config/settings.json")
    if systemctl --user is-active --quiet "$service"; then service_was_active=yes; fi
fi
if [[ "$fresh" == yes || "$force_update" == yes ]]; then
    reset_state check
fi
check_connection
if [[ "$fresh" == yes ]]; then
    if [[ "$autostart" == keep ]]; then
        if systemctl --user is-enabled --quiet "$service"; then autostart=yes; else autostart=no; fi
    fi
    if [[ -e /etc/systemd/system/taskrail-executor.service || -d /opt/taskrail-executor ]]; then
        executor_reset=yes
        sudo -v
        sudo bash "$source_dir/deploy/reset-executor.sh" --replacement="$source_dir" --check
    fi
fi
if ! systemctl --user stop "$service"; then
    # A first install may not have a unit. A failure to stop a loaded unit is fatal.
    if [[ $(systemctl --user show "$service" --property=LoadState --value) != not-found ]]; then
        echo 'Could not stop the service; release was not switched' >&2
        exit 1
    fi
fi
if [[ "$force_update" == yes ]] && ! lock_workflows; then
    # A standalone task still holds the lock. Restore the previous managed service.
    if [[ "$service_was_active" == yes ]]; then systemctl --user start "$service"; fi
    exit 1
fi
if [[ "$executor_reset" == yes ]]; then
    sudo bash "$source_dir/deploy/reset-executor.sh" --replacement="$source_dir"
fi
if [[ "$fresh" == yes ]]; then
    systemctl --user disable "$service" 2>/dev/null || true
fi
if [[ "$fresh" == yes || "$force_update" == yes ]]; then
    reset_state remove || {
        status=$?
        # Validation under the workflow lock can see files created during shutdown.
        if [[ "$status" == 2 && "$service_was_active" == yes ]]; then systemctl --user start "$service"; fi
        exit "$status"
    }
    mkdir -p "$app_dir/releases" "$config_dir"
fi
