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
"$python_bin" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || {
    echo 'Python 3.10+ is required' >&2
    exit 2
}
# Run main() of a module of the incoming release, with isolated imports.
module_main='import importlib, sys; sys.path.insert(0, sys.argv.pop(1)); importlib.import_module(sys.argv.pop(1)).main()'
run_module() {
    "$python_bin" -I -B -c "$module_main" "$source_dir" "$@"
}
check_connection() {
    local environment=$config_dir/service.env
    if [[ -f "$staging/config/service.env" ]]; then environment=$staging/config/service.env; fi
    systemd-run --user --pipe --wait --quiet --collect \
        --property="EnvironmentFile=$environment" --property=UMask=0077 --working-directory="$release" \
        "$release/venv/bin/python" -I -B -c "$module_main" "$release" taskrail.deployment.settings_check \
        "$config_dir" "$staging/config" "$fresh"
}
# Serialize installers. Never switch releases underneath an active workflow.
# shellcheck source=deploy/install-locks.sh
source "$source_dir/deploy/install-locks.sh"
mkdir -p "$app_dir/releases" "$config_dir" "$unit_dir" "$HOME/.local/bin"
# A fresh reset removes app_dir, so preparation lives beside it, on the same filesystem.
staging=$(mktemp -d "$HOME/.local/share/.taskrail-stage-XXXXXXXX")
release=$staging/release
mkdir "$release"
next_config=
cleanup() {
    rm -rf -- "$staging"
    rm -f -- "$app_dir/current.next.$$"
    if [[ -n "$next_config" ]]; then rm -rf -- "$next_config"; fi
    if [[ -n ${installed_release:-} && ! "$app_dir/current" -ef "$installed_release" ]]; then
        rm -rf -- "$installed_release"
    fi
}
trap cleanup EXIT
run_module taskrail.deployment.release_files application "$source_dir" "$release"
"$python_bin" -m venv --without-pip "$release/venv"
version=$("$release/venv/bin/python" -I -B -c \
    'import sys; sys.path.insert(0, sys.argv[1]); from taskrail.web.service import ApplicationService; from taskrail.core.release import VERSION; print(VERSION)' "$release")
# Configuration, copied roles and the environment are prepared before any reset.
prepare_options=()
[[ "$fresh" == yes ]] && prepare_options+=(--fresh)
[[ "$apply_settings" == yes ]] && prepare_options+=(--apply-settings)
[[ -n "$opencode_path" ]] && prepare_options+=("--opencode=$opencode_path")
run_module taskrail.deployment.settings_stage "$source_dir" "$config_dir" "$initial_settings" "$app_dir" "$agent_mode" "${prepare_options[@]}" "$staging/config"
# shellcheck source=deploy/fresh.sh
source "$source_dir/deploy/fresh.sh"
installed_release=$(mktemp -d "$app_dir/releases/$version-XXXXXXXX")
rmdir "$installed_release"
mv -- "$release" "$installed_release"
release=$installed_release
# Keep atomic replacements on the configuration filesystem, including first installs.
next_config=$(mktemp -d "$config_dir/.install-XXXXXXXX")
for name in settings.json cli-check.sha256; do
    if [[ -f "$staging/config/$name" ]]; then mv -- "$staging/config/$name" "$next_config/"; fi
done
publish_config() {
    if [[ -f "$next_config/$1" ]]; then mv -Tf -- "$next_config/$1" "$config_dir/$1"; fi
}
cp -a -- "$staging/config/." "$config_dir/"
publish_config settings.json
ln -s "$release" "$app_dir/current.next.$$"
mv -Tf "$app_dir/current.next.$$" "$app_dir/current"
install -m 644 "$release/deploy/taskrail.service" "$unit_dir/$service"
install -m 755 "$release/deploy/taskrail" "$HOME/.local/bin/taskrail"
systemctl --user daemon-reload
if [[ "$fresh" == yes || "$force_update" == yes ]]; then
    systemctl --user reset-failed "$service"
fi
case "$autostart" in
    yes) systemctl --user enable "$service" ;;
    no) systemctl --user disable "$service" ;;
esac
# Workers must not inherit the installer's workflow lock.
flock -u 9
exec 9>&-
systemctl --user restart "$service"
systemctl --user is-active --quiet "$service"
publish_config cli-check.sha256
"$release/venv/bin/python" -I -B -c \
    'import sys; sys.path.insert(0, sys.argv.pop(1)); from taskrail.deployment.releases import main; main()' \
    "$release" "$app_dir" "$config_dir/settings.json"
if [[ "$boot" == yes ]]; then
    # Explicit opt-in: this affects the user's service manager, not just Taskrail.
    loginctl enable-linger "$(id -un)" || {
        echo 'Taskrail is running, but boot startup needs an administrator to enable user lingering.' >&2
        exit 1
    }
fi
printf 'Autostart: '
systemctl --user is-enabled "$service" || true
printf 'Installed Taskrail %s\nUI: http://127.0.0.1:8787 (default port)\nSettings: %s/settings.json\n' "$version" "$config_dir"
if ! PATH=/usr/bin:/bin command -v bwrap >/dev/null; then
    echo 'Install bubblewrap (for example: sudo apt install bubblewrap) to sandbox local commands. Without it the host command policy applies.'
fi

if [[ "${executor_reset:-no}" == yes ]]; then
    sudo bash "$source_dir/deploy/install-executor.sh" --client="$(id -un)" --autostart=disable
    echo "SSH inventory and host keys were erased. Configure them before starting the executor."
fi
