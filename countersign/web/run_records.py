"""Run actions that record an operator choice in the run directory or start an epic task."""

from functools import partial
from types import MappingProxyType

from countersign.interactions import approval_policy
from countersign.web import epic_launch, epic_tasks, run_groups

RECORDS = MappingProxyType(
    {
        "done": partial(run_groups.mark, done=True),
        "reopen": partial(run_groups.mark, done=False),
        "revoke_auto_approve": approval_policy.revoke,
        "epic_auto_on": partial(epic_tasks.set_auto, enabled=True),
        "epic_auto_off": partial(epic_tasks.set_auto, enabled=False),
    }
)
EPIC_NEXT = "epic_next"
PAUSES = MappingProxyType({"epic_pause": True, "epic_unpause": False})
ACTIONS = frozenset((*RECORDS, *PAUSES, EPIC_NEXT))


def record(launcher, run, payload):
    """Apply one action; the next epic task needs the launcher, a pause names its task."""
    action = payload["action"]
    if action == EPIC_NEXT:
        return epic_launch.start_next(launcher, run)
    paused = PAUSES.get(action)
    if paused is not None:
        return epic_tasks.set_pause(run, payload["task"], paused)
    return RECORDS[action](run)
