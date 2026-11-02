"""Exercise the approval route of local commands on a host that can sandbox them."""

from unittest.mock import patch

from taskrail.infrastructure import sandbox
from taskrail.interactions import approval_policy


def without_sandbox(test):
    """Local commands wait for decisions: no working bubblewrap and host_commands "ask"."""
    for patcher in (
        patch.object(sandbox, "mode", return_value=None),
        patch.object(approval_policy, "host_automatic", return_value=False),
    ):
        patcher.start()
        test.addCleanup(patcher.stop)
