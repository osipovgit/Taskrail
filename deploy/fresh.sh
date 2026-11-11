#!/usr/bin/env bash
# Switch only after validating the incoming release and draining the managed service.
reset_state() {
    run_module taskrail.deployment.fresh "$1" "$source_dir" "$initial_settings" \
        --incoming-settings "$staging/config/settings.json" "${profile_option[@]}"
}
profile_option=()
executor_reset=no
service_was_active=no
if [[ -n "$reset_mode" ]]; then
    if [[ -f "$config_dir/service.env" ]]; then
        # The previous service may have generated profiles outside the shell's CLI config.
        old_profiles=$(service_python "$config_dir/service.env" "$module_main" "$release" taskrail.deployment.reset_paths "$config_dir")
        profile_option=(--profile-directory "$old_profiles")
    fi
    reset_state check
    if systemctl --user is-active --quiet "$service"; then service_was_active=yes; fi
    if [[ "$autostart" == keep ]]; then
        if systemctl --user is-enabled --quiet "$service"; then autostart=yes; else autostart=no; fi
    fi
fi
check_connection
if [[ "$reset_mode" == fresh ]]; then
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
if [[ "$reset_mode" == force-update ]] && ! lock_workflows; then
    # A standalone task still holds the lock. Restore the previous managed service.
    if [[ "$service_was_active" == yes ]]; then systemctl --user start "$service"; fi
    exit 1
fi
if [[ "$executor_reset" == yes ]]; then
    sudo bash "$source_dir/deploy/reset-executor.sh" --replacement="$source_dir"
fi
if [[ -n "$reset_mode" ]]; then
    reset_state remove || {
        status=$?
        # Validation under the workflow lock can see files created during shutdown.
        if [[ "$status" == 2 && "$service_was_active" == yes ]]; then systemctl --user start "$service"; fi
        exit "$status"
    }
    mkdir -p "$app_dir/releases" "$config_dir"
fi
