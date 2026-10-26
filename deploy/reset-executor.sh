#!/usr/bin/env bash
# Full reset of the separately installed SSH executor; explicit sudo is required.
set -euo pipefail
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
trap 'leave_maintenance "$marker"' EXIT
# The journal of a running or uncertain action is never deleted: reconcile it first.
begin_maintenance "$marker" /var/lib/taskrail-executor /etc/systemd/system/taskrail-executor.service RUNNING UNKNOWN
systemctl disable taskrail-executor.service 2>/dev/null || true
rm -f -- /etc/systemd/system/taskrail-executor.service /usr/local/bin/taskrail-executor-approve
rm -rf -- /opt/taskrail-executor /etc/taskrail-executor /var/lib/taskrail-executor /run/taskrail-executor /etc/systemd/system/taskrail-executor.service.d
systemctl daemon-reload
