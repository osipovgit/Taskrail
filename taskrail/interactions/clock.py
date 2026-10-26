"""Active stage time excludes operator waiting but includes command execution."""

import time

from taskrail.application.artifacts import save_run


class StageClock:
    """One monotonic deadline for all turns of a stage."""

    def __init__(self, limit):
        self.limit = limit
        self.started = time.monotonic()
        self.paused = 0

    def elapsed(self):
        """Return active elapsed time."""
        return time.monotonic() - self.started - self.paused

    def remaining(self):
        """Never grant another full hour on tool completion."""
        return max(0, self.limit - self.elapsed())


class ApprovalPause:
    """Restore clock state on a decision, interruption or exception."""

    def __init__(self, session):
        self.session = session
        self.started = None

    def __enter__(self):
        self.started = time.monotonic()
        record = self.session.active[1]
        record.update(status="WAITING_APPROVAL", elapsed_seconds=self.session.clock.elapsed())
        save_run(self.session.environment["run"], self.session.state)

    def __exit__(self, *_exception):
        self.session.clock.paused += time.monotonic() - self.started
        record = self.session.active[1]
        record.update(status="RUNNING", paused_seconds=self.session.clock.paused)
        save_run(self.session.environment["run"], self.session.state)
