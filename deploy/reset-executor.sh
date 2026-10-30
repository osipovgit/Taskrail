#!/usr/bin/env bash
# Full reset of the separately installed SSH executor; explicit sudo is required.
set -euo pipefail
replacement_source=''
check_only=no
for argument in "$@"; do
    case "$argument" in
        --replacement=*) replacement_source=${argument#*=} ;;
        --check) check_only=yes ;;
        *)
            echo 'Usage: reset-executor.sh [--replacement=RELEASE_DIRECTORY] [--check]' >&2
            exit 2
            ;;
    esac
done
[[ $EUID -eq 0 ]] || {
    echo 'Run as root' >&2
    exit 2
}
# shellcheck source=deploy/executor-maintenance.sh
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/executor-maintenance.sh"
lock_executor_maintenance /run/taskrail-executor-maintenance.lock
/usr/bin/python3 -I - <<'PY'
from pathlib import Path
for raw in ('/opt/taskrail-executor', '/etc/taskrail-executor', '/var/lib/taskrail-executor', '/run/taskrail-executor'):
    path = Path(raw)
    if path.resolve() != path:
        raise SystemExit('Refuse executor directory symlink: ' + raw)
PY
marker=/etc/taskrail-executor/maintenance
staging=''
cleanup() {
    leave_maintenance "$marker"
    [[ -z "$staging" ]] || rm -rf -- "$staging"
}
trap cleanup EXIT
# Combined fresh installation must prove the replacement before discarding the old
# executor. Standalone reset has no replacement and keeps its existing semantics.
if [[ -n "$replacement_source" ]]; then
    mkdir -p /opt/taskrail-executor
    staging=$(mktemp -d /opt/taskrail-executor/.reset-XXXXXXXX)
    prepare_executor_package "$replacement_source/taskrail" "$staging"
    mkdir "$staging/config"
    /usr/bin/python3 -I -B -c \
        'import sys; sys.path.insert(0, sys.argv.pop(1)); from taskrail.deployment.executor_check import main; main()' \
        "$staging" "$staging/config" "$replacement_source"
    for name in executor-service ssh-askpass taskrail-executor-approve taskrail-executor.service executor-jenkins.example.json; do
        cp -- "$replacement_source/deploy/$name" "$staging/$name"
    done
fi
if [[ "$check_only" == yes ]]; then
    require_settled /var/lib/taskrail-executor RUNNING UNKNOWN
    exit 0
fi
# The journal of a running or uncertain action is never deleted: reconcile it first.
begin_maintenance "$marker" /var/lib/taskrail-executor /etc/systemd/system/taskrail-executor.service RUNNING UNKNOWN
systemctl disable taskrail-executor.service 2>/dev/null || true
rm -f -- /etc/systemd/system/taskrail-executor.service /usr/local/bin/taskrail-executor-approve
rm -rf -- /opt/taskrail-executor /etc/taskrail-executor /var/lib/taskrail-executor /run/taskrail-executor /etc/systemd/system/taskrail-executor.service.d
systemctl daemon-reload
