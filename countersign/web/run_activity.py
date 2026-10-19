"""Whether a run or one of its projects is active, from the run locks."""

import json

from countersign.application import run_locks
from countersign.web.history import read_artifact

RUN_INDEX = "run.json"


def run_sources(run):
    """The source projects a run locks; isolated runs lock the sources of their worktrees."""
    index = json.loads(read_artifact(run, RUN_INDEX))
    worktrees = index.get("worktrees") or {}
    if worktrees:
        return [entry["source"] for entry in worktrees.values()]
    return list(index.get("roots", {}).values())


def run_busy(run):
    """The run's worker or another run on one of its projects is active."""
    if run_locks.busy(run_locks.lock_path(run_locks.RUN, run)):
        return True
    sources = run_sources(run) if (run / RUN_INDEX).is_file() else []
    locks = [run_locks.lock_path(run_locks.ROOT, source) for source in sources]
    return any(map(run_locks.busy, locks))


class BusyError(ValueError):
    """The run, or a project it uses, is active."""


def require_idle(live, run, sources):
    """Neither the run nor any of its projects may be active."""
    if run is not None and run_active(live, run):
        raise BusyError("This run is still active")
    active = {source for running in live.values() for source in running}
    for source in map(str, sources):
        if source in active or run_locks.busy(run_locks.lock_path(run_locks.ROOT, source)):
            raise BusyError(f"Another task is running on {source}. Wait until it stops.")


def run_active(live, run):
    """A worker of this launcher or any other process holds the run."""
    return run in live or run_locks.busy(run_locks.lock_path(run_locks.RUN, run))
