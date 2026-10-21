"""The delivery record beside a code-changing run: its phase runs and the confirmation.

The web interface writes epic.json when it starts a phase run and when the operator
confirms the change. The SSH route reads it, so a server check changes servers only
when the operator confirmed the change the check belongs to.
"""

import json
import re

EPIC = "epic.json"
RUN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


def read(run):
    """The record of a run, or an empty record."""
    path = run / EPIC
    if path.is_file() and not path.is_symlink():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def server_checks_confirmed(run, change):
    """run is the server check run of the run named change, and the operator confirmed it."""
    if not isinstance(change, str) or not RUN_NAME.fullmatch(change):
        return False
    record = read(run.parent / change)
    started = record.get("phases", {}).get("server")
    return bool(record.get("confirmed")) and started == run.name
