#!/usr/bin/env bash
# Full reset of the separately installed SSH executor; explicit sudo is required.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root' >&2; exit 2; }
/usr/bin/python3 -I - <<'PY'
import json
from pathlib import Path
for path in Path('/var/lib/countersign-executor').glob('*.json'):
    if json.loads(path.read_text()).get('status') in ('RUNNING', 'UNKNOWN'):
        raise SystemExit('Reconcile running/unknown remote actions before a fresh installation')
for raw in ('/opt/countersign-executor', '/etc/countersign-executor', '/var/lib/countersign-executor', '/run/countersign-executor'):
    path = Path(raw)
    if path.resolve() != path:
        raise SystemExit('Refuse executor directory symlink: ' + raw)
PY
systemctl stop countersign-executor.service
systemctl disable countersign-executor.service 2>/dev/null || true
rm -f -- /etc/systemd/system/countersign-executor.service /usr/local/bin/countersign-executor-approve
rm -rf -- /opt/countersign-executor /etc/countersign-executor /var/lib/countersign-executor /run/countersign-executor /etc/systemd/system/countersign-executor.service.d
systemctl daemon-reload
