"""Bounded retry policy of one stage: format repair, access and transport recovery."""

from countersign.application import access_recovery, evidence, prompts
from countersign.application.attempt_launch import role_of
from countersign.observability.progress import say

IMPLEMENTER = "implementer"
TRANSPORT = frozenset(("TIMEOUT", "INCOMPLETE", "PROCESS_ERROR"))
TRANSPORT_KEY = "transport"
FORMAT_KEY = "format"


class Retries:
    """Decide whether a failed attempt may run again and what the next attempt gets."""

    def __init__(self, attempts):
        """Restore access recovery history from earlier records of the same stage."""
        self.attempts = attempts
        self.stage = attempts.workflow.flow["stage"]
        self.access = access_recovery.restore(attempts.workflow.state, self.stage)
        self.counts = {TRANSPORT_KEY: 0, FORMAT_KEY: 0}

    def mode(self):
        """The record mode of the next attempt."""
        if self.attempts.format_only:
            return "format-repair"
        if self.access.count:
            return "access-recovery"
        if self.attempts.recovery:
            return "research-recovery"
        return "model"

    def allowed(self, outcome):
        """Return True after preparing the next attempt, False to stop the stage."""
        status = outcome["status"]
        if status == "INVALID_RESULT":
            return self.format_repair(outcome)
        if status == "BLOCKED_PERMISSION":
            return self.access_recovery(outcome)
        return status in TRANSPORT and self.transport_retry()

    def format_repair(self, outcome):
        """One repair of the response format; edits stay denied, even for the implementer."""
        if self.counts[FORMAT_KEY] >= 1:
            return False
        self.counts[FORMAT_KEY] += 1
        state = self.attempts.workflow.state
        self.attempts.format_only = True
        self.attempts.request = prompts.repair(
            outcome["final_text"],
            outcome["contract_error"],
            role_of(self.stage),
            state.get("contract_version"),
            state["requirements"],
        )
        return True

    def access_recovery(self, outcome):
        """Continue a read-only stage with allowed sources after a new denial."""
        workflow = self.attempts.workflow
        if self.stage == IMPLEMENTER or self.attempts.format_only:
            return False
        if not self.access.accept(outcome, workflow.config["timeout"]):
            return False
        self.attempts.recovery = evidence.load_index(workflow.run)
        denied = access_recovery.denied_calls(outcome)
        correction = access_recovery.correction(denied, workflow.config["roots"])
        self.attempts.request = "{0}{1}".format(self.attempts.request, correction)
        say("  Access denied; continuing with allowed sources ({0}/2)".format(self.access.count))
        return True

    def transport_retry(self):
        """Read-only stages retry interrupted transports with recorded evidence."""
        workflow = self.attempts.workflow
        limit = 0 if self.stage == IMPLEMENTER else workflow.config["read_retries"]
        if self.counts[TRANSPORT_KEY] >= limit or self.access.count:
            return False
        self.counts[TRANSPORT_KEY] += 1
        if not self.attempts.format_only:
            self.attempts.recovery = evidence.load_index(workflow.run)
        return True
