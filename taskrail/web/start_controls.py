"""Controls that start a worker for a run: continue, restart and follow-up.

A run on an overlapping project holds them back; the view says which one.
"""

from taskrail.application import check_parents
from taskrail.application.checkpoints import resume_available
from taskrail.web import run_family

RUN_INDEX = "run.json"


def starts(run, state, activity):
    """Each start control, and why they wait for another run."""
    free = not activity.held and not activity.waiting
    can_resume, reason = resume_available(run, state)
    follow_up = run_family.can_follow_up(run, state)
    blocked = not activity.held and (can_resume or follow_up)
    return dict(
        followup=free and follow_up,
        restart=restart(run, state, activity),
        resume=can_resume and free,
        resume_budget=can_resume and free,
        resume_reason=reason,
        waiting_for=activity.waiting if blocked else None,
    )


def restart(run, state, activity):
    """A restart draft opens in the editor; a task or phase restart starts at once."""
    if state.get(check_parents.PHASE) == "correction":
        return False
    if not (run / RUN_INDEX).is_file() or activity.held:
        return False
    return not activity.waiting or not state.get(check_parents.PHASE)
