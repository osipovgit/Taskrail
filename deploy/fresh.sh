#!/usr/bin/env bash
# Sourced with the installer and workflow locks held. Never infer project ownership.
[[ "$fresh" == yes ]] || return 0
if [[ "$autostart" == keep ]]; then
    if systemctl --user is-enabled --quiet "$service"; then autostart=yes; else autostart=no; fi
fi
# Validate the complete deletion set before stopping or deleting anything.
"$python_bin" - "$source_dir" "$initial_settings" <<'PY'
import json
import os
from pathlib import Path

home = Path.home().resolve()
managed = [home / suffix for suffix in (
    '.local/share/countersign', '.config/countersign', '.local/state/countersign',
)]
settings = managed[1] / 'settings.json'
options = json.loads(settings.read_text()) if settings.is_file() else {}
custom = Path(options.get('run_base', managed[2] / 'runs')).expanduser()
custom = custom if custom.is_absolute() else settings.parent / custom
if custom.exists() and custom != managed[2] / 'runs':
    if custom.resolve() != custom or custom in (home, Path('/')):
        raise SystemExit('Unsafe custom run_base; no files deleted')
    for child in custom.iterdir():
        if child.name not in ('.trash', '.submissions') and not (child / 'run.json').is_file():
            raise SystemExit('Custom run_base contains unrecognized files; no files deleted: ' + str(child))
    managed.append(custom)
for directory in managed:
    if directory.resolve() != directory:
        raise SystemExit('Refuse managed directory symlink: ' + str(directory))
    for protected in (Path(os.sys.argv[1]).resolve(), Path(os.sys.argv[2]).resolve() if os.sys.argv[2] else None):
        if protected and (protected == directory or directory in protected.parents):
            raise SystemExit('Extract release and supplied settings outside reset directories')
# A configured history root must never contain a declared source project.
for history in (managed[2] / 'runs', custom):
    if history.is_dir():
        for index in history.glob('*/run.json'):
            roots = json.loads(index.read_text()).get('roots', {})
            for source in map(Path, roots.values()):
                if any(source == target or source in target.parents or target in source.parents for target in managed):
                    raise SystemExit('Reset paths overlap a declared project; no files deleted')
print('Fresh installation will remove:')
for directory in managed:
    print('  ' + str(directory))
PY
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
"$python_bin" - "$source_dir" <<'PY'
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from countersign.infrastructure.agent_sync import launch_settings

home = Path.home().resolve()
app = home / '.local/share/countersign'
config = home / '.config/countersign'
state = home / '.local/state/countersign'
settings = config / 'settings.json'
options = json.loads(settings.read_text()) if settings.is_file() else {}
custom = Path(options.get('run_base', state / 'runs')).expanduser()
custom = custom if custom.is_absolute() else config / custom
try:
    # The same directory rules as the workflow that wrote the profiles.
    profiles = launch_settings(options, config)['destination']
except ValueError:
    profiles = home / '.config/opencode/agent'
# Only Countersign-owned generated profiles, not the underlying CLI's credentials/config.
if profiles.is_dir() and not profiles.is_symlink():
    for profile in profiles.glob('*.md'):
        if profile.is_symlink():
            continue
        if profile.name.startswith('countersign-') and 'Managed Countersign workflow' in profile.read_text():
            profile.unlink()
def remove(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
if custom.exists() and state not in custom.parents and custom != state:
    remove(custom)
# Keep locked inodes until installation finishes; removing them would defeat flock.
for directory, lock in ((app, 'install.lock'), (state, 'live.lock'), (config, None)):
    for child in directory.iterdir():
        if child.name != lock:
            remove(child)
for entry in (
    home / '.config/systemd/user/countersign.service',
    home / '.config/systemd/user/countersign.service.d',
    home / '.local/bin/countersign',
    home / '.cache/countersign',
):
    remove(entry)
PY
systemctl --user daemon-reload
systemctl --user reset-failed "$service" 2>/dev/null || true
mkdir -p "$app_dir/releases" "$config_dir" "$state_dir/runs"
agent_mode=bundled
