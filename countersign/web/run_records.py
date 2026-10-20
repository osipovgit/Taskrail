"""Run actions that only record an operator choice in the run directory."""

from functools import partial
from types import MappingProxyType

from countersign.interactions import approval_policy
from countersign.web import run_groups

RECORDS = MappingProxyType(
    {
        "done": partial(run_groups.mark, done=True),
        "reopen": partial(run_groups.mark, done=False),
        "revoke_auto_approve": approval_policy.revoke,
    }
)
ACTIONS = frozenset(RECORDS)


def record(run, action):
    """Apply one recording action and return its response."""
    return RECORDS[action](run)
