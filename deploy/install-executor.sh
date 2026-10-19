#!/usr/bin/env bash
# Install the isolated, system-wide SSH executor from a reviewed release.
set -euo pipefail
client_user=''
autostart=keep
for argument in "$@"; do
  case "$argument" in
    --client=*) client_user=${argument#*=} ;;
    --autostart=enable|--autostart=disable|--autostart=keep) autostart=${argument#*=} ;;
    *) printf 'Usage: sudo bash deploy/install-executor.sh --client=USER --autostart=enable|disable|keep\n' >&2; exit 2 ;;
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
source_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
# Refuse an update while remote effects may still be in flight.
/usr/bin/python3 -I - <<'PY'
import json
from pathlib import Path
for path in Path('/var/lib/countersign-executor').glob('*.json'):
    if json.loads(path.read_text()).get('status') == 'RUNNING':
        raise SystemExit('An executor action is running. Wait before updating.')
PY
getent group countersign-executor >/dev/null || groupadd --system countersign-executor
id countersign-executor >/dev/null 2>&1 || useradd --system --gid countersign-executor --home-dir /nonexistent --shell /usr/sbin/nologin countersign-executor
getent group countersign-executor-clients >/dev/null || groupadd --system countersign-executor-clients
if [[ $client_user == countersign-executor ]] || id -nG -- "$client_user" | tr ' ' '\n' | grep -qx countersign-executor; then
  printf 'The application account must not belong to the private countersign-executor group.\n' >&2
  exit 2
fi
usermod -a -G countersign-executor-clients "$client_user"
usermod -a -G countersign-executor-clients countersign-executor
systemctl stop countersign-executor.service 2>/dev/null || true
install -d -m 0755 -o root -g root /opt/countersign-executor /opt/countersign-executor/deploy
# The directory contains only this application's package, never target sources.
rm -rf -- /opt/countersign-executor/countersign
cp -R -- "$source_root/countersign" /opt/countersign-executor/
chown -R root:root /opt/countersign-executor/countersign
chmod -R go-w /opt/countersign-executor/countersign
for name in executor-service ssh-askpass; do
  install -m 0755 -o root -g root "$source_root/deploy/$name" "/opt/countersign-executor/deploy/$name"
done
install -m 0755 -o root -g root "$source_root/deploy/countersign-executor-approve" /usr/local/bin/countersign-executor-approve
install -d -m 0750 -o root -g countersign-executor /etc/countersign-executor
install -d -m 0700 -o countersign-executor -g countersign-executor /var/lib/countersign-executor
if [[ ! -f /etc/countersign-executor/hosts.json ]]; then
  install -m 0640 -o root -g countersign-executor "$source_root/deploy/executor-hosts.example.json" /etc/countersign-executor/hosts.json
fi
install -m 0640 -o root -g countersign-executor "$source_root/deploy/executor-jenkins.example.json" /etc/countersign-executor/jenkins.json.example
if [[ ! -f /etc/countersign-executor/known_hosts ]]; then
  install -m 0640 -o root -g countersign-executor /dev/null /etc/countersign-executor/known_hosts
fi
private_files=(/etc/countersign-executor/hosts.json /etc/countersign-executor/known_hosts)
[[ -e /etc/countersign-executor/jenkins.json || -L /etc/countersign-executor/jenkins.json ]] && private_files+=(/etc/countersign-executor/jenkins.json)
for private_file in "${private_files[@]}"; do
  if [[ -L $private_file || ! -f $private_file ]]; then
    printf 'Executor configuration must use regular files, not symlinks.\n' >&2
    exit 2
  fi
  chown root:countersign-executor "$private_file"
  chmod 0640 "$private_file"
done
sed "s/@CLIENT_UID@/$client_uid/g" "$source_root/deploy/countersign-executor.service" > /etc/systemd/system/countersign-executor.service
chmod 0644 /etc/systemd/system/countersign-executor.service
systemctl daemon-reload
case "$autostart" in
  enable) systemctl enable countersign-executor.service ;;
  disable) systemctl disable countersign-executor.service ;;
esac
printf '%s\n' \
  'Executor installed. Existing credentials and host keys were preserved.' \
  'Use sudoedit /etc/countersign-executor/hosts.json and /etc/countersign-executor/known_hosts.' \
  'For Jenkins, copy jenkins.json.example to jenkins.json in the same directory and edit it.' \
  'Verify host keys through a trusted channel; unknown keys fail closed.' \
  'Then run: sudo systemctl start countersign-executor.service' \
  'Log out and back in before restarting Countersign so its process gets the client group.' \
  'Do NOT give the Countersign account passwordless sudo or add it to the countersign-executor group.'
