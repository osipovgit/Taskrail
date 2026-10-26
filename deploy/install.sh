#!/usr/bin/env bash
# Install/update from an extracted trusted release, as the application user.
set -euo pipefail
umask 077
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
python_bin=${PYTHON:-python3}
app_dir="$HOME/.local/share/taskrail"
config_dir="$HOME/.config/taskrail"
state_dir="$HOME/.local/state/taskrail"
unit_dir="$HOME/.config/systemd/user"
service=taskrail.service
# shellcheck source=deploy/options.sh
source "$source_dir/deploy/options.sh"
systemctl --user show-environment >/dev/null
"$python_bin" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required"'
# An installation under the previous project name (Countersign) moves to the Taskrail
# folders once: settings, roles and run history are kept, never copied or deleted.
previous_state="$HOME/.local/state/countersign"
previous_config="$HOME/.config/countersign"
if [[ -d $previous_state && ! -e $state_dir ]]; then
    exec 6>"$previous_state/live.lock"
    flock -w "$wait_seconds" 6 || {
        echo 'Stop the active task of the Countersign installation first' >&2
        exit 1
    }
    systemctl --user disable --now countersign.service 2>/dev/null || true
    exec 6>&-
    mv -T -- "$previous_state" "$state_dir"
fi
if [[ -d $previous_config && ! -e $config_dir ]]; then
    mv -T -- "$previous_config" "$config_dir"
fi
if [[ -e $unit_dir/countersign.service ]]; then
    systemctl --user disable --now countersign.service 2>/dev/null || true
    rm -f -- "$unit_dir/countersign.service" "$HOME/.local/bin/countersign"
fi
mkdir -p "$app_dir/releases" "$config_dir" "$state_dir/runs" "$unit_dir" "$HOME/.local/bin"
# Serialize installers. Never switch releases underneath an active workflow.
exec 8>"$app_dir/install.lock"
flock -n 8 || {
    echo 'Another installation is running' >&2
    exit 1
}
exec 9>"$state_dir/live.lock"
echo "Waiting up to $wait_seconds seconds for the active workflow to finish..."
flock -w "$wait_seconds" 9 || {
    echo 'Stop the active task in the UI and wait before updating' >&2
    exit 1
}
# shellcheck source=deploy/fresh.sh
source "$source_dir/deploy/fresh.sh"
version=$(PYTHONPATH="$source_dir" "$python_bin" -c 'from taskrail.core.version import VERSION; print(VERSION)')
release=$(mktemp -d "$app_dir/releases/$version-XXXXXXXX")
# Copy the application only; project source roots and task history are never copied.
tar -C "$source_dir" --exclude='__pycache__' --exclude='*.pyc' -cf - \
    taskrail deploy pyproject.toml README.md LICENSE |
    tar -C "$release" -xf -
"$python_bin" -m venv --without-pip "$release/venv"
PYTHONPATH="$release" "$release/venv/bin/python" -c 'from taskrail.web.service import ApplicationService'
# Initialize persistent configuration once. Updates preserve user settings and agents.
"$python_bin" -I -c \
    'import sys; sys.path.insert(0, sys.argv.pop(1)); from taskrail.deployment.settings_init import main; main()' \
    "$source_dir" "$source_dir" "$config_dir" "$initial_settings" "$app_dir" "$agent_mode"
# Stop the UI only after validating the new release and obtaining the execution lock.
systemctl --user stop "$service" 2>/dev/null || {
    if systemctl --user is-active --quiet "$service"; then
        echo 'Service could not be stopped; release was not switched' >&2
        exit 1
    fi
}
ln -s "$release" "$app_dir/current.next.$$"
mv -Tf "$app_dir/current.next.$$" "$app_dir/current"
install -m 644 "$release/deploy/taskrail.service" "$unit_dir/$service"
install -m 755 "$release/deploy/taskrail" "$HOME/.local/bin/taskrail"
systemctl --user daemon-reload
case "$autostart" in
    yes) systemctl --user enable "$service" ;;
    no) systemctl --user disable "$service" ;;
esac
# Workers must not inherit the installer's workflow lock.
flock -u 9
exec 9>&-
systemctl --user restart "$service"
systemctl --user is-active --quiet "$service"
if [[ "$boot" == yes ]]; then
    # Explicit opt-in: this affects the user's service manager, not just Taskrail.
    loginctl enable-linger "$(id -un)" || {
        echo 'Taskrail is running, but boot startup needs an administrator to enable user lingering.' >&2
        exit 1
    }
fi
printf 'Autostart: '
systemctl --user is-enabled "$service" || true
printf 'Installed Taskrail %s\nUI: http://127.0.0.1:8787 (default port)\nSettings: %s/settings.json\nHistory: %s/runs\n' "$version" "$config_dir" "$state_dir"

if [[ "${executor_reset:-no}" == yes ]]; then
    sudo bash "$source_dir/deploy/install-executor.sh" --client="$(id -un)" --autostart=disable
    echo "SSH inventory and host keys were erased. Configure them before starting the executor."
fi
