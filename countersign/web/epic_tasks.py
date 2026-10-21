"""The tasks of a split goal and the runs that carry them out.

A run that ended as TASKS_READY is an epic: its reviewed plan steps are the tasks.
epic.json beside it links each task to the run started for it and keeps the
auto-continue choice. Everything else is read from those runs.
"""

import json
from types import MappingProxyType

from countersign.core import delivery_record, task_graph
from countersign.web import lifecycle, run_groups, run_sources
from countersign.web.history import read_artifact

EPIC = delivery_record.EPIC
PAUSE = "pause_before"
STATUS = "status"
READY = "TASKS_READY"
FINISHED = frozenset(("READY_FOR_REVIEW", "NO_CHANGES_REQUIRED"))
ACTIVE = frozenset(("STARTING", "RUNNING"))
SUMMARY_LIMIT = 400
TITLE_LIMIT = 120
IDENTIFIER = "id"
NOT_STARTED = MappingProxyType(dict(status=None, summary="", changed_files=(), done=False))
STEP_FIELDS = MappingProxyType(
    {
        "goal": "action",
        "checks": "checks",
        "files": "files",
        "depends_on": "depends_on",
        "requirements": "criteria",
    }
)
# Fields of plans written as plan.md; older plans lack them.
PLAN_FIELDS = MappingProxyType(dict(done_when=(), notes="", scopes=()))


def record(run):
    """Task links, phases and choices; before the first change, auto-continue follows the run.

    Runs started since automatic splitting continue on their own; older splits do not.
    """
    path = run / EPIC
    if path.is_file() and not path.is_symlink():
        return json.loads(path.read_text())
    index = run / "run.json"
    state = json.loads(index.read_text()) if index.is_file() else {}
    return dict(tasks={}, auto_continue=state.get("auto_continue") is True, pause_before=[])


def tasks(run, state):
    """Each planned task in execution order, with the outcome of its run once started."""
    plan = json.loads(read_artifact(run, state["results"]["plan"]))
    epic = record(run)
    steps = {step[IDENTIFIER]: step for step in plan["steps"]}
    ordered = task_graph.order(plan["steps"])
    return [entry(run.parent, steps[name], epic) for name in ordered]


def entry(base, step, epic):
    """One task: its plan step and, once started, its run's status and outcome."""
    child = epic["tasks"].get(step[IDENTIFIER])
    task = {key: step[source] for key, source in STEP_FIELDS.items()}
    for key, default in PLAN_FIELDS.items():
        task[key] = step.get(key, default)
    task.update(NOT_STARTED, id=step[IDENTIFIER], run=child)
    task["pause_before"] = step[IDENTIFIER] in epic.get(PAUSE, [])
    task["title"] = step.get("title") or short_title(task["goal"])
    if child:
        task.update(outcome(base / child))
    return task


def short_title(action):
    """The text before the first colon of a task action, on one line."""
    title = " ".join(action.split(":", 1)[0].split())
    return title[:TITLE_LIMIT]


def outcome(child):
    """Status, bounded summary and changed files of a task run; its launch until it exists."""
    index = child / "run.json"
    if not index.is_file():
        return {STATUS: launch_status(child)}
    state = json.loads(index.read_text())
    summary = state.get("summary", "")[:SUMMARY_LIMIT]
    status = lifecycle.display_status(child, state)
    outcome = dict(status=status, summary=summary, done=run_groups.marked(child, state))
    outcome["changed_files"] = state.get("changed_files", [])
    return outcome


def launch_status(child):
    """STARTING while the worker starts; the launcher's record once the start failed."""
    launch = run_sources.launch_record(child.parent / ".submissions" / child.name)
    return launch.get(STATUS, "STARTING")
