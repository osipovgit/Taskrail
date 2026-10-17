#!/usr/bin/env bash
# Install/update from an extracted trusted release, as the application user.
set -euo pipefail
umask 077
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
python_bin=${PYTHON:-python3}
app_dir="$HOME/.local/share/countersign"
config_dir="$HOME/.config/countersign"
state_dir="$HOME/.local/state/countersign"
unit_dir="$HOME/.config/systemd/user"
service=countersign.service
source "$source_dir/deploy/options.sh"
systemctl --user show-environment >/dev/null
"$python_bin" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required"'
mkdir -p "$app_dir/releases" "$config_dir" "$state_dir/runs" "$unit_dir" "$HOME/.local/bin"
# Serialize installers. Never switch releases underneath an active workflow.
exec 8>"$app_dir/install.lock"
flock -n 8 || { echo 'Another installation is running' >&2; exit 1; }
exec 9>"$state_dir/live.lock"
echo "Waiting up to $wait_seconds seconds for the active workflow to finish..."
flock -w "$wait_seconds" 9 || { echo 'Stop the active task in the UI and wait before updating' >&2; exit 1; }
source "$source_dir/deploy/fresh.sh"
version=$(PYTHONPATH="$source_dir" "$python_bin" -c 'from countersign import __version__; print(__version__)')
release=$(mktemp -d "$app_dir/releases/$version-XXXXXXXX")
# Copy the application only; project source roots and task history are never copied.
tar -C "$source_dir" --exclude='__pycache__' --exclude='*.pyc' -cf - \
    countersign deploy docs pyproject.toml README.md LICENSE |
    tar -C "$release" -xf -
"$python_bin" -m venv --without-pip "$release/venv"
PYTHONPATH="$release" "$release/venv/bin/python" -c 'from countersign.web.service import ApplicationService'
# Initialize persistent configuration once. Updates preserve user settings and agents.
"$python_bin" - "$source_dir" "$config_dir" "$initial_settings" "$app_dir" "$agent_mode" <<'PY'
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

source, config, supplied, app, agent_mode = sys.argv[1:]
source, config, app = Path(source), Path(config), Path(app)
target = config / "settings.json"
if not target.exists():
    initial = Path(supplied).expanduser().resolve() if supplied else source / "countersign/settings.json"
    settings = json.loads(initial.read_text())
    settings["timeout_seconds"] = 3600
    command = settings.get("command", ["opencode"])
    if not isinstance(command, list) or not command or not all(isinstance(arg, str) for arg in command):
        raise ValueError("settings.command must be a nonempty argv array")
    executable = shutil.which(command[0])
    if executable is None:
        raise ValueError("Agent CLI command not found on PATH: " + command[0])
    settings["command"] = [executable, *command[1:]]
    if supplied:
        agents = Path(settings.get("agent_source", initial.parent / "agents")).expanduser()
        agents = agents if agents.is_absolute() else initial.parent / agents
        if not (config / "agents").exists():
            shutil.copytree(agents, config / "agents")
        settings["agent_source"] = str(config / "agents")
        for key in ("agent_directory", "run_base"):
            if key in settings:
                folder = Path(settings[key]).expanduser()
                settings[key] = str(folder if folder.is_absolute() else initial.parent / folder)
    else:
        settings["agent_source"] = str(app / "current/countersign/agents")
    target.write_text(json.dumps(settings, indent=2) + "\n")
    target.chmod(0o600)
else:
    json.loads(target.read_text())
if agent_mode == "bundled":
    previous = target.read_bytes()
    settings = json.loads(previous)
    settings["agent_source"] = str(app / "current/countersign/agents")
    backup = config / ("settings.json.backup-" + hashlib.sha256(previous).hexdigest()[:16])
    if not backup.exists():
        backup.write_bytes(previous)
        backup.chmod(0o600)
    temporary = config / "settings.json.next"
    temporary.write_text(json.dumps(settings, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(target)
    print("Using bundled roles; previous settings saved to " + str(backup))
environment = config / "service.env"
if not environment.exists():
    captured = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    captured = captured.replace("\\", "\\\\").replace('"', '\\"')
    if "\n" in captured or "\r" in captured:
        raise ValueError("PATH must not contain newlines")
    environment.write_text('PATH="' + captured + '"\nCOUNTERSIGN_WEB_PORT=8787\n')
    environment.chmod(0o600)
PY
# Stop the UI only after validating the new release and obtaining the execution lock.
systemctl --user stop "$service" 2>/dev/null || {
    if systemctl --user is-active --quiet "$service"; then
        echo 'Service could not be stopped; release was not switched' >&2
        exit 1
    fi
}
ln -s "$release" "$app_dir/current.next.$$"
mv -Tf "$app_dir/current.next.$$" "$app_dir/current"
install -m 644 "$release/deploy/countersign.service" "$unit_dir/$service"
install -m 755 "$release/deploy/countersign" "$HOME/.local/bin/countersign"
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
    # Explicit opt-in: this affects the user's service manager, not just Countersign.
    loginctl enable-linger "$(id -un)" || {
        echo 'Countersign is running, but boot startup needs an administrator to enable user lingering.' >&2
        exit 1
    }
fi
printf 'Autostart: '
systemctl --user is-enabled "$service" || true
printf 'Installed Countersign %s\nUI: http://127.0.0.1:8787 (default port)\nSettings: %s/settings.json\nHistory: %s/runs\n' "$version" "$config_dir" "$state_dir"

if [[ "${executor_reset:-no}" == yes ]]; then
    sudo bash "$source_dir/deploy/install-executor.sh" --client="$(id -un)" --autostart=disable
    echo "SSH inventory and host keys were erased. Configure them before starting the executor."
fi
