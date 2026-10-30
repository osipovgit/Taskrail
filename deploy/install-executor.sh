#!/usr/bin/env bash
# Install the isolated, system-wide SSH executor from a reviewed release.
set -euo pipefail
client_user=''
autostart=keep
for argument in "$@"; do
    case "$argument" in
        --client=*) client_user=${argument#*=} ;;
        --autostart=enable | --autostart=disable | --autostart=keep) autostart=${argument#*=} ;;
        *)
            printf 'Usage: sudo bash deploy/install-executor.sh --client=USER --autostart=enable|disable|keep\n' >&2
            exit 2
            ;;
    esac
done
if [[ $EUID -ne 0 || -z $client_user ]]; then
    printf 'Run with sudo and an explicit --client=USER.\n' >&2
    exit 2
fi
client_uid=$(id -u -- "$client_user")
if [[ $client_uid -eq 0 ]]; then
    printf 'The orchestrator must run under an ordinary user account.\n' >&2
    exit 2
fi
command -v python3 >/dev/null
/usr/bin/python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required"'
command -v ssh >/dev/null
command -v systemctl >/dev/null
command -v runuser >/dev/null
source_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=deploy/executor-maintenance.sh
source "$source_root/deploy/executor-maintenance.sh"
lock_executor_maintenance /run/taskrail-executor-maintenance.lock
release=/opt/taskrail-executor
config=/etc/taskrail-executor
state=/var/lib/taskrail-executor
unit_file=/etc/systemd/system/taskrail-executor.service
marker=$config/maintenance
/usr/bin/python3 -I -B -c \
    'import sys; sys.path.insert(0, sys.argv.pop(1)); from taskrail.deployment.executor_check import main; main()' \
    "$source_root" "$config" "$source_root" "$release" "$state"
getent group taskrail-executor >/dev/null || groupadd --system taskrail-executor
id taskrail-executor >/dev/null 2>&1 || useradd --system --gid taskrail-executor --home-dir /nonexistent --shell /usr/sbin/nologin taskrail-executor
getent group taskrail-executor-clients >/dev/null || groupadd --system taskrail-executor-clients
if [[ $client_user == taskrail-executor ]] || id -nG -- "$client_user" | tr ' ' '\n' | grep -qx taskrail-executor; then
    printf 'The application account must not belong to the private taskrail-executor group.\n' >&2
    exit 2
fi
usermod -a -G taskrail-executor-clients "$client_user"
usermod -a -G taskrail-executor-clients taskrail-executor
install -d -m 0755 -o root -g root "$release" "$release/deploy"
install -d -m 0750 -o root -g taskrail-executor "$config"
# Prepare the new package before anything stops; the swap below is a rename. The
# directory contains only this application's package, never target sources.
staging=$(mktemp -d "$release/.taskrail.XXXXXX")
cleanup() {
    leave_maintenance "$marker"
    rm -rf -- "$staging"
}
trap cleanup EXIT
prepare_executor_package "$source_root/taskrail" "$staging"
# Parse all effective private configuration before maintenance or package replacement.
/usr/bin/python3 -I -B -c \
    'import sys; sys.path.insert(0, sys.argv.pop(1)); from taskrail.deployment.executor_check import main; main()' \
    "$staging" "$config" "$source_root" "$release" "$state"
# All deployment artifacts must be readable and prepared before stopping the service.
mkdir "$staging/deploy"
for name in executor-service ssh-askpass taskrail-executor-approve; do
    install -m 0755 -o root -g root "$source_root/deploy/$name" "$staging/deploy/$name"
done
sed "s/@CLIENT_UID@/$client_uid/g" "$source_root/deploy/taskrail-executor.service" >"$staging/service"
# No new submissions or approvals from here on; refuse while an action runs; the stop
# must succeed, and the journal is checked again after it.
begin_maintenance "$marker" "$state" "$unit_file" RUNNING
if [[ -d $release/taskrail ]]; then
    mv -- "$release/taskrail" "$staging/previous"
fi
if ! mv -- "$staging/taskrail" "$release/taskrail"; then
    [[ -d $staging/previous ]] && mv -- "$staging/previous" "$release/taskrail"
    printf 'The new package could not be moved into place; the previous one was kept.\n' >&2
    exit 1
fi
for name in executor-service ssh-askpass; do
    install -m 0755 -o root -g root "$staging/deploy/$name" "$release/deploy/$name"
done
install -m 0755 -o root -g root "$staging/deploy/taskrail-executor-approve" /usr/local/bin/taskrail-executor-approve
install -d -m 0700 -o taskrail-executor -g taskrail-executor "$state"
if [[ ! -f /etc/taskrail-executor/hosts.json ]]; then
    install -m 0640 -o root -g taskrail-executor "$source_root/deploy/executor-hosts.example.json" /etc/taskrail-executor/hosts.json
fi
install -m 0640 -o root -g taskrail-executor "$source_root/deploy/executor-jenkins.example.json" /etc/taskrail-executor/jenkins.json.example
if [[ ! -f /etc/taskrail-executor/known_hosts ]]; then
    install -m 0640 -o root -g taskrail-executor /dev/null /etc/taskrail-executor/known_hosts
fi
private_files=(/etc/taskrail-executor/hosts.json /etc/taskrail-executor/known_hosts)
[[ -e /etc/taskrail-executor/jenkins.json || -L /etc/taskrail-executor/jenkins.json ]] && private_files+=(/etc/taskrail-executor/jenkins.json)
for private_file in "${private_files[@]}"; do
    if [[ -L $private_file || ! -f $private_file ]]; then
        printf 'Executor configuration must use regular files, not symlinks.\n' >&2
        exit 2
    fi
    chown root:taskrail-executor "$private_file"
    chmod 0640 "$private_file"
done
install -m 0644 -o root -g root "$staging/service" "$unit_file"
systemctl daemon-reload
case "$autostart" in
    enable) systemctl enable taskrail-executor.service ;;
    disable) systemctl disable taskrail-executor.service ;;
esac
printf '%s\n' \
    'Executor installed. Existing credentials and host keys were preserved.' \
    'Use sudoedit /etc/taskrail-executor/hosts.json and /etc/taskrail-executor/known_hosts.' \
    'For Jenkins, copy jenkins.json.example to jenkins.json in the same directory and edit it.' \
    'Verify host keys through a trusted channel; unknown keys fail closed.' \
    'Then run: sudo systemctl start taskrail-executor.service' \
    'Log out and back in before restarting Taskrail so its process gets the client group.' \
    'Do NOT give the Taskrail account passwordless sudo or add it to the taskrail-executor group.'
