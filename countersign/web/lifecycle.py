"""Cooperative stop requests and reversible history removal."""

import json

from countersign.application import run_locks
from countersign.application.checkpoints import budget_paused, resume_available
from countersign.core.files import atomic_json
from countersign.interactions import approvals
from countersign.web.history import read_artifact

RUN_INDEX = "run.json"
STATUS = "status"
ACTIVE_STATUSES = frozenset(("STARTING", "RUNNING"))


def request_stop(run):
    """Request checkpoint-preserving interruption without signalling a saved PID."""
    index = json.loads(read_artifact(run, RUN_INDEX))
    if index.get(STATUS) != "RUNNING":
        raise ValueError("Only a running task can be stopped")
    atomic_json(run / "stop.request", {"requested": True})
    return dict(id=run.name, status="STOP_REQUESTED")


def trash_run(base, run):
    """Move artifacts while holding the run's lock, so its worker cannot start meanwhile."""
    with run_locks.lock_file(run_locks.lock_path(run_locks.RUN, run)) as stream:
        if not run_locks.locked(stream, run_locks.EXCLUSIVE):
            raise ValueError("Only stopped task histories can be deleted")
        HistoryRemoval(base, run).move()
    return dict(id="", status="DELETED")


class HistoryRemoval:
    """Validate all storage before moving source-independent task artifacts."""

    def __init__(self, base, run):
        self.run = run
        self.folders = self.launch_folders(base)
        self.trash = base / ".trash"

    def validate(self):
        """Include failed launches, but exclude active and unknown histories."""
        indices = [json.loads(read_artifact(folder, "launch.json")) for folder in self.folders]
        if self.run.exists():
            current = json.loads(read_artifact(self.run, RUN_INDEX))
            # The execution lock is held: a terminal run supersedes stale launch records.
            if current.get(STATUS) not in ACTIVE_STATUSES:
                indices = []
            indices.append(current)
        active = any(index.get(STATUS) in ACTIVE_STATUSES for index in indices)
        if not indices or active:
            raise ValueError("Only stopped task histories can be deleted")
        if self.trash.is_symlink():
            raise ValueError("Trash must not be a symlink")

    def move(self):
        """Keep the run accessible if moving a launcher record fails."""
        self.validate()
        destination = self.trash / self.run.name
        destination.mkdir(parents=True, exist_ok=False)
        for folder in self.folders:
            folder.rename(destination / folder.name)
        if self.run.exists():
            self.run.rename(destination / "run")

    def matches_launch(self, folder):
        """Ignore damaged unrelated launcher records."""
        if folder.is_symlink() or not folder.is_dir():
            return False
        try:
            manifest = json.loads(read_artifact(folder, "launch.json"))
        except (OSError, ValueError):
            return False
        return manifest.get("id") == self.run.name

    def launch_folders(self, base):
        """Select valid launcher records without following storage symlinks."""
        submissions = base / ".submissions"
        if submissions.is_symlink():
            raise ValueError("Submission storage must not be a symlink")
        if not submissions.exists():
            return []
        return [folder for folder in submissions.iterdir() if self.matches_launch(folder)]


def require_resumable(run):
    """Keep the same checkpoint eligibility rules for both interfaces."""
    state = json.loads(read_artifact(run, RUN_INDEX))
    allowed, reason = resume_available(run, state)
    if not allowed:
        raise ValueError(reason)


def actions(run, state, busy):
    """Expose state-dependent controls without weakening checkpoint checks."""
    idle = not busy
    running = state.get(STATUS) == "RUNNING"
    requested = running and (run / "stop.request").exists()
    can_resume, reason = resume_available(run, state)
    return dict(
        stop=running and not requested,
        stop_requested=requested,
        delete=not running and state.get(STATUS) != "STARTING" and idle,
        followup=(run / RUN_INDEX).is_file() and not running and idle,
        restart=(run / RUN_INDEX).is_file() and idle,
        resume=can_resume and idle,
        resume_budget=can_resume and idle,
        budget_paused=budget_paused(state),
        resume_reason=reason,
    )


def pending_approval(run):
    """Expose only the current exact request for operator review."""
    return approvals.load(run)


def display_status(run, state):
    """Highlight tasks that need a decision, independently of worker liveness."""
    return "WAITING_APPROVAL" if pending_approval(run) else state.get(STATUS)
