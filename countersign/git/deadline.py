"""Carry one stage deadline through every Git preflight and subprocess."""

import subprocess
import time
from contextvars import ContextVar

from countersign.core import control

CONTEXT = ContextVar("git_stage_deadline", default=None)


class Deadline:
    """All nested Git probes share the remaining active stage allowance."""

    def __init__(self, remaining, run):
        self.bounds = (time.monotonic() + remaining, run)
        self.token = None

    def __enter__(self):
        self.token = CONTEXT.set(self.bounds)

    def __exit__(self, *_exception):
        CONTEXT.reset(self.token)


def check(argv):
    """Check before launch and while waiting; Stop remains cooperative."""
    current = CONTEXT.get()
    if current is not None:
        expires, run = current
        control.check_stop(run)
        if time.monotonic() >= expires:
            raise subprocess.TimeoutExpired(argv, 0)
