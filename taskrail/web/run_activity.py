"""Whether a run or a run on an overlapping project is active, from the run locks."""

import json
from typing import NamedTuple

from taskrail.application import lock_resources, run_locks
from taskrail.web import epic_tasks, run_family
from taskrail.web.history import read_artifact

RUN_INDEX = "run.json"


def run_sources(run):
    """The source projects a run locks; isolated runs lock the sources of their worktrees."""
    index = json.loads(read_artifact(run, RUN_INDEX))
    worktrees = index.get("worktrees") or {}
    if worktrees:
        return [entry["source"] for entry in worktrees.values()]
    return list(index.get("roots", {}).values())


class Activity(NamedTuple):
    """What keeps a run's controls from acting now."""

    # The run's own worker is active.
    held: bool = False
    # A task or phase run of its split or delivery is active.
    family: bool = False
    # Why a new worker of this run cannot start yet: a run on an overlapping project.
    waiting: str | None = None


def activity(run):
    """The run's own worker, the runs of its split and the projects it would lock."""
    held = run_held(run)
    members = run_family.members(epic_tasks.record(run))
    family = any(run_held(run.parent / name) for name in members)
    sources = run_sources(run) if (run / RUN_INDEX).is_file() else []
    return Activity(held, family, None if held else run_locks.conflict(sources))


class BusyError(ValueError):
    """The run, or a project it uses, is active."""


def require_idle(live, run, sources):
    """Neither the run nor a run on an overlapping project or repository may be active.

    live holds the sources of workers this launcher started, which may not hold their
    locks yet.
    """
    if run is not None and run_active(live, run):
        raise BusyError("This run is still active")
    started = (lock_resources.contested(running, sources) for running in live.values())
    reason = next(filter(None, started), None) or run_locks.conflict(sources)
    if reason:
        raise BusyError(f"{reason}. Wait until it stops.")


def run_active(live, run):
    """A worker of this launcher or any other process holds the run."""
    return run in live or run_held(run)


def run_held(run):
    """Another process holds the run's lock."""
    with run_locks.lock_file(run_locks.lock_path(run_locks.RUN, run)) as stream:
        return not run_locks.locked(stream, run_locks.EXCLUSIVE)
