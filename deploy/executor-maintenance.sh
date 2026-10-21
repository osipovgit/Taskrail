# Maintenance steps shared by the executor installer and reset (sourced, not run).
# Paths are arguments, so the order of the steps can be tested without root.
executor_unit=countersign-executor.service

# While the marker exists the service refuses new submissions and approvals.
enter_maintenance() { # MARKER
  if [[ -d ${1%/*} ]]; then
    : >"$1"
  fi
}

leave_maintenance() { # MARKER
  rm -f -- "$1"
}

# Fail while a ticket has one of the given statuses; nothing is changed.
require_settled() { # STATE_DIRECTORY STATUS...
  /usr/bin/python3 -I - "$@" <<'PY'
import json
import sys
from pathlib import Path

state, statuses = Path(sys.argv[1]), set(sys.argv[2:])
for path in sorted(state.glob('*.json')):
    status = json.loads(path.read_text()).get('status')
    if status in statuses:
        raise SystemExit(f'Executor action {path.stem} is {status}; reconcile it first. Nothing was changed.')
PY
}

# Stop an installed service; a failed or incomplete stop fails the caller.
stop_executor() { # UNIT_FILE
  if [[ ! -e $1 ]]; then
    return 0
  fi
  systemctl stop "$executor_unit"
  if systemctl is-active --quiet "$executor_unit"; then
    printf 'The executor did not stop. Nothing was changed.\n' >&2
    return 1
  fi
}

# Refuse new work, check the journal, stop the service and check again: an action an
# older service approved between the first check and the stop is caught by the second.
# The caller removes the marker on exit (leave_maintenance in its EXIT trap).
begin_maintenance() { # MARKER STATE_DIRECTORY UNIT_FILE STATUS...
  local marker=$1 state=$2 unit_file=$3
  shift 3
  enter_maintenance "$marker"
  require_settled "$state" "$@"
  stop_executor "$unit_file"
  require_settled "$state" "$@"
}
