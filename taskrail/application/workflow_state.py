"""Run-wide state shared by the stage loop and its attempts."""

from taskrail.application.artifacts import finish_stage
from taskrail.application.source_guard import SourceGuard
from taskrail.core import control
from taskrail.core.files import atomic_json, digest

STAGE = "stage"
ALLOWED = "allowed"
ACTIVE = "active"
PROFILE_SUFFIX = 8
FLOW_KEYS = (STAGE, "plan", "feedback", ALLOWED, "plan_repairs", "repair_count")


class Workflow:
    """Configuration, persisted state, integrity guard and stage flow of one locked run."""

    def __init__(self, config, run, state, request):
        """Start at planning; a continuation replaces the flow from its checkpoint."""
        self.config = config
        self.run = run
        self.state = state
        self.guard = SourceGuard(config["roots"])
        self.flow = dict.fromkeys(FLOW_KEYS)
        self.flow.update(stage="planner", allowed=[], plan_repairs=0, repair_count=0)
        self.runtime = dict(
            debug=request["debug"],
            resumed=bool(request["resume"]),
            active=None,
            profiles=set(),
            recovery=None,
            note=control.check_note(request.get("note")),
            profile_suffix=digest(str(run).encode())[:PROFILE_SUFFIX],
        )

    def checkpoint(self, expected=None):
        """Persist the flow with the fingerprints a continuation must find."""
        fingerprints = self.guard.expected if expected is None else expected
        atomic_json(
            self.run / "checkpoint.json",
            dict(
                {key: self.flow[key] for key in FLOW_KEYS},
                expected=fingerprints,
                git_before=self.guard.git_before,
                task_hash=digest(self.config["task_text"].encode()),
            ),
        )

    def writable(self):
        """Only the implementer may change approved files."""
        if self.flow[STAGE] == "implementer":
            return self.flow[ALLOWED]
        return []

    def open_record(self, active):
        """Remember the stage record that must be finished if the run stops."""
        self.runtime[ACTIVE] = active

    def finish_active(self, status, verdict=None, diagnostics=None):
        """Finish the open stage record exactly once."""
        active = self.runtime[ACTIVE]
        self.runtime[ACTIVE] = None
        outcome = dict(status=status, result=verdict, diagnostics=diagnostics)
        finish_stage(self.run, self.state, active, outcome)
