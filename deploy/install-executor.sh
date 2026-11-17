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
command -v ssh-keygen >/dev/null
command -v ssh-keyscan >/dev/null
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
if [[ $client_user == taskrail-executor ]] || id -nG -- "$client_user" | tr ' ' '\n' | grep -qx taskrail-executor; then
    printf 'The application account must not belong to the private taskrail-executor group.\n' >&2
    exit 2
fi
install -d -m 0755 -o root -g root "$release" "$release/deploy"
install -d -m 0750 -o root -g taskrail-executor "$config"
if [[ ! -d $config/inventories ]]; then
    install -d -m 0750 -o root -g taskrail-executor "$config/inventories"
fi
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
    "$staging" "$config" "$staging" "$release" "$state"
# All deployment artifacts must be readable and prepared before stopping the service.
sed "s/@CLIENT_UID@/$client_uid/g" "$staging/deploy/taskrail-executor.service" >"$staging/service"
# No new submissions or approvals from here on; refuse while an action runs; the stop
# must succeed, and the journal is checked again after it.
socket_unit=taskrail-executor.socket
sed "s/@CLIENT_UID@/$client_uid/g" "$staging/deploy/$socket_unit" >"$staging/socket"
socket_active=no
if [[ -e /etc/systemd/system/taskrail-executor.socket ]] && systemctl is-active --quiet "$socket_unit"; then socket_active=yes; fi
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
    echo '{}' >"$staging/hosts.json"
    install -m 0640 -o root -g taskrail-executor "$staging/hosts.json" /etc/taskrail-executor/hosts.json
fi
install -m 0640 -o root -g taskrail-executor "$staging/deploy/executor-jenkins.example.json" /etc/taskrail-executor/jenkins.json.example
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
install -m 0644 -o root -g root "$staging/socket" /etc/systemd/system/taskrail-executor.socket
# The socket now owns activation, including after an upgrade from a standalone unit.
if [[ -e "$unit_file" ]]; then systemctl disable taskrail-executor.service; fi
install -m 0644 -o root -g root "$staging/service" "$unit_file"
systemctl daemon-reload
leave_maintenance "$marker"
case "$autostart" in
    enable) systemctl enable --now "$socket_unit" ;;
    disable) systemctl disable "$socket_unit" ;;
    keep) if [[ "$socket_active" == yes ]]; then systemctl start "$socket_unit"; fi ;;
esac
echo "Executor installed. SSH remembers new hosts on first contact. To preconfigure trusted keys, use /etc/taskrail-executor/known_hosts."
