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
# Serialize installers. Never switch releases underneath an active workflow.
# shellcheck source=deploy/install-locks.sh
source "$source_dir/deploy/install-locks.sh"
mkdir -p "$app_dir/releases" "$config_dir" "$state_dir/runs" "$unit_dir" "$HOME/.local/bin"
# An invalid import must not destroy an existing installation during --fresh.
preflight=(--check)
[[ "$fresh" == yes ]] && preflight+=(--fresh)
"$python_bin" -I -c \
    'import sys; sys.path.insert(0, sys.argv.pop(1)); from taskrail.deployment.settings_init import main; main()' \
    "$source_dir" "$source_dir" "$config_dir" "$initial_settings" "$app_dir" "$agent_mode" "${preflight[@]}"
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
if ! PATH=/usr/bin:/bin command -v bwrap >/dev/null; then
    echo 'Install bubblewrap (for example: sudo apt install bubblewrap) so agents run local commands in a sandbox without approval; until then each one waits for you.'
fi

if [[ "${executor_reset:-no}" == yes ]]; then
    sudo bash "$source_dir/deploy/install-executor.sh" --client="$(id -un)" --autostart=disable
    echo "SSH inventory and host keys were erased. Configure them before starting the executor."
fi
