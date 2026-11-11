#!/usr/bin/env bash
# Serialize installation and workflow maintenance.
# Inherited descriptors are reused only when they name the expected lock inode.
mkdir -p "$app_dir" "$state_dir"
if [[ ! /proc/self/fd/8 -ef "$app_dir/install.lock" ]]; then
    exec 8>"$app_dir/install.lock"
fi
flock -n 8 || {
    echo 'Another installation is running' >&2
    exit 1
}
if [[ ! /proc/self/fd/9 -ef "$state_dir/live.lock" ]]; then
    exec 9>"$state_dir/live.lock"
fi
lock_workflows() {
    if [[ "$wait_seconds" -gt 0 ]]; then
        echo "Waiting up to $wait_seconds seconds for the active workflow to finish..."
    fi
    flock -w "$wait_seconds" 9 || {
        echo 'Stop the active task in the UI or CLI and wait before updating' >&2
        return 1
    }
}
if [[ "$force_update" == no ]]; then
    lock_workflows
fi
