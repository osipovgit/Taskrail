"""Exercise the approval route of local commands on a host that can sandbox them."""

from unittest.mock import patch

from taskrail.infrastructure import sandbox


def without_sandbox(test):
    """Local commands wait for decisions, as on a host without a working bubblewrap."""
    patcher = patch.object(sandbox, "mode", return_value=None)
    patcher.start()
    test.addCleanup(patcher.stop)
