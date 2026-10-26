"""Every run started for a task or phase, so earlier attempts stay visible in one line each."""

from countersign.core import delivery_record
from countersign.web import epic_tasks
from countersign.web.run_family import PHASE_ATTEMPTS

REASON_LIMIT = 160


def phase_attempts(epic, name):
    """The runs started for one phase, oldest first."""
    recorded = epic.get(PHASE_ATTEMPTS, {}).get(name)
    if recorded:
        return list(recorded)
    current = epic.get("phases", {}).get(name, "")
    return [current] if delivery_record.RUN_NAME.fullmatch(current) else []


def remember_phases(epic):
    """Keep the current phase runs in their attempt lists before a phase starts again."""
    for name in epic.get("phases", {}):
        epic.setdefault(PHASE_ATTEMPTS, {}).setdefault(name, phase_attempts(epic, name))


def earlier(base, runs, current):
    """Attempts before the current run, oldest first, each reduced to one line."""
    return [brief(base / name) for name in runs if name != current]


def brief(child):
    """Run, status and the first line of its summary."""
    known = epic_tasks.outcome(child)
    lines = known.get("summary", "").strip().splitlines()
    reason = lines[0][:REASON_LIMIT] if lines else ""
    return dict(run=child.name, status=known[epic_tasks.STATUS], reason=reason)


def add_task_attempts(run, epic, tasks):
    """Each task of a split view gets the attempts before its current run."""
    for task in tasks:
        started = delivery_record.attempts(epic, task["id"])
        task["attempts"] = earlier(run.parent, started, task["run"])


def add_phase_attempts(run, epic, views):
    """Each phase view gets the attempts before its current run."""
    for name, view in views.items():
        started = phase_attempts(epic, name)
        view["attempts"] = earlier(run.parent, started, view["run"])
