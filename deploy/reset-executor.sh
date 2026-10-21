#!/usr/bin/env bash
# Full reset of the separately installed SSH executor; explicit sudo is required.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root' >&2; exit 2; }
/usr/bin/python3 -I - <<'PY'
from pathlib import Path
for raw in ('/opt/countersign-executor', '/etc/countersign-executor', '/var/lib/countersign-executor', '/run/countersign-executor'):
    path = Path(raw)
    if path.resolve() != path:
        raise SystemExit('Refuse executor directory symlink: ' + raw)
PY
# shellcheck source=deploy/executor-maintenance.sh
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/executor-maintenance.sh"
marker=/etc/countersign-executor/maintenance
trap 'leave_maintenance "$marker"' EXIT
# The journal of a running or uncertain action is never deleted: reconcile it first.
begin_maintenance "$marker" /var/lib/countersign-executor /etc/systemd/system/countersign-executor.service RUNNING UNKNOWN
systemctl disable countersign-executor.service 2>/dev/null || true
rm -f -- /etc/systemd/system/countersign-executor.service /usr/local/bin/countersign-executor-approve
rm -rf -- /opt/countersign-executor /etc/countersign-executor /var/lib/countersign-executor /run/countersign-executor /etc/systemd/system/countersign-executor.service.d
systemctl daemon-reload
