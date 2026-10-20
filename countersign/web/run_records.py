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
ACTIONS = frozenset((*RECORDS, EPIC_NEXT))


def record(launcher, run, action):
    """Apply one action and return its response; the next epic task needs the launcher."""
    if action == EPIC_NEXT:
        return epic_launch.start_next(launcher, run)
    return RECORDS[action](run)
