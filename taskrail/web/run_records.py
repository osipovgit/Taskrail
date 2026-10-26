"""Run actions that record an operator choice in the run directory or start an epic task."""

from functools import partial
from types import MappingProxyType

from taskrail.interactions import approval_policy
from taskrail.web import (
    delivery_launch,
    epic_launch,
    epic_record,
    integration_launch,
    run_groups,
)

RECORDS = MappingProxyType(
    {
        "done": partial(run_groups.mark, done=True),
        "reopen": partial(run_groups.mark, done=False),
        "revoke_auto_approve": approval_policy.revoke,
        "epic_auto_on": partial(epic_record.set_auto, enabled=True),
        "epic_auto_off": partial(epic_record.set_auto, enabled=False),
    }
)
EPIC_NEXT = "epic_next"
CONFIRM = "confirm"
INTEGRATION = "integration_review"
PAUSES = MappingProxyType({"epic_pause": True, "epic_unpause": False})
LAUNCHES = MappingProxyType(
    {
        EPIC_NEXT: epic_launch.start_next,
        CONFIRM: delivery_launch.confirm,
        INTEGRATION: integration_launch.repeat,
    }
)
ACTIONS = frozenset((*RECORDS, *PAUSES, *LAUNCHES))


def record(launcher, run, payload):
    """Apply one action; launches need the launcher, task actions name their task."""
    action = payload["action"]
    launch = LAUNCHES.get(action)
    if launch:
        return launch(launcher, run)
    paused = PAUSES.get(action)
    if paused is not None:
        return epic_record.set_pause(run, payload["task"], paused)
    return RECORDS[action](run)
