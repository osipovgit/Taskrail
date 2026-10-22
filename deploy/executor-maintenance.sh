#!/usr/bin/env bash
# Maintenance steps shared by the executor installer and reset (sourced, not run).
# Paths are arguments, so the order of the steps can be tested without root.
executor_unit=countersign-executor.service
executor_marker_owned=''

# The root-owned lock is outside all installation/reset targets and lives until exit.
lock_executor_maintenance() { # LOCK_FILE
  umask 077
  exec 7>"$1"
  flock -n 7 || { printf 'Another executor installation or reset is running.\n' >&2; return 1; }
}

# While the marker exists the service refuses new submissions and approvals.
enter_maintenance() { # MARKER
  if [[ -d ${1%/*} ]]; then
    if ! (set -o noclobber; : >"$1") 2>/dev/null; then
      printf 'Executor maintenance marker exists; inspect the interrupted maintenance first.\n' >&2
      return 1
    fi
    executor_marker_owned=$1
  fi
}

leave_maintenance() { # MARKER
  if [[ $executor_marker_owned == "$1" ]]; then
    rm -f -- "$1"
    executor_marker_owned=''
  fi
}

# The dedicated service must be able to import even a privately extracted release.
prepare_executor_package() { # SOURCE_PACKAGE STAGING_DIRECTORY
  cp -R -- "$1" "$2/countersign"
  if [[ -n $(find "$2/countersign" -type l -print -quit) ]]; then
    printf 'Executor packages must not contain symlinks.\n' >&2
    return 1
  fi
  chown -R root:root "$2/countersign"
  find "$2/countersign" -type d -exec chmod 0755 {} +
  find "$2/countersign" -type f -exec chmod 0644 {} +
  chmod 0755 "$2"
  runuser -u countersign-executor -- /usr/bin/python3 -I -B -c \
    'import sys; sys.path.insert(0, sys.argv[1]); import countersign.executor.service; import countersign.executor.approval' "$2"
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
