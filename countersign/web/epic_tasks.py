"""The tasks of a split goal and the runs that carry them out.

A run that ended as TASKS_READY is an epic: its reviewed plan steps are the tasks.
epic.json beside it links each task to the run started for it and keeps the
auto-continue choice. Everything else is read from those runs.
"""

import json
from types import MappingProxyType

from countersign.core.files import atomic_json
from countersign.web import lifecycle
from countersign.web.history import read_artifact

EPIC = "epic.json"
STATUS = "status"
READY = "TASKS_READY"
FINISHED = frozenset(("READY_FOR_REVIEW", "NO_CHANGES_REQUIRED"))
ACTIVE = frozenset(("STARTING", "RUNNING"))
SUMMARY_LIMIT = 400
TITLE_LIMIT = 120
IDENTIFIER = "id"
NOT_STARTED = MappingProxyType(dict(status=None, summary="", changed_files=()))
STEP_FIELDS = MappingProxyType(
    {"goal": "action", "checks": "checks", "files": "files", "depends_on": "depends_on"}
)


def record(run):
    """Task links and the auto-continue choice; empty before the first task starts."""
    path = run / EPIC
    if path.is_file() and not path.is_symlink():
        return json.loads(path.read_text())
    return dict(tasks={}, auto_continue=False)


def set_auto(run, enabled):
    """Turn automatic continuation after each successful task on or off."""
    epic = record(run)
    epic["auto_continue"] = enabled
    atomic_json(run / EPIC, epic)
    return dict(id=run.name, status="AUTO_CONTINUE_ON" if enabled else "AUTO_CONTINUE_OFF")


def tasks(run, state):
    """Each planned task with the status and outcome of its run, if one was started."""
    plan = json.loads(read_artifact(run, state["results"]["plan"]))
    links = record(run)["tasks"]
    return [entry(run.parent, step, links) for step in plan["steps"]]


def entry(base, step, links):
    """One task: its plan step and, once started, its run's status and outcome."""
    child = links.get(step[IDENTIFIER])
    task = {key: step[source] for key, source in STEP_FIELDS.items()}
    task.update(NOT_STARTED, id=step[IDENTIFIER], run=child)
    task["title"] = short_title(task["goal"])
    if child:
        task.update(outcome(base / child))
    return task


def short_title(action):
    """The text before the first colon of a task action, on one line."""
    title = " ".join(action.split(":", 1)[0].split())
    return title[:TITLE_LIMIT]


def outcome(child):
    """Status, bounded summary and changed files of a task run; STARTING until it exists."""
    index = child / "run.json"
    if not index.is_file():
        return {STATUS: "STARTING"}
    state = json.loads(index.read_text())
    summary = state.get("summary", "")[:SUMMARY_LIMIT]
    status = lifecycle.display_status(child, state)
    return dict(status=status, summary=summary, changed_files=state.get("changed_files", []))
