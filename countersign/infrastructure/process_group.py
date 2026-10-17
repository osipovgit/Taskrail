"""Stop a process group started with start_new_session."""

import os
import signal
import time

GRACE_SECONDS = 2
POLL_SECONDS = 0.05


def stop_group(pid):
    """SIGTERM the group, give every member a grace period, then SIGKILL survivors."""
    if not signal_group(pid, signal.SIGTERM):
        return
    deadline = time.monotonic() + GRACE_SECONDS
    while time.monotonic() < deadline:
        if not signal_group(pid, 0):
            return
        time.sleep(POLL_SECONDS)
    signal_group(pid, signal.SIGKILL)


def signal_group(pid, signum):
    """Return False once the group no longer exists."""
    try:
        os.killpg(pid, signum)
    except ProcessLookupError:
        return False
    return True
