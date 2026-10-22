"""Bounded retry policy of one stage: format repair, access and transport recovery."""

from countersign.application import access_recovery, evidence, plan_recovery, prompts
from countersign.application.attempt_launch import role_of
from countersign.infrastructure import context_overflow
from countersign.observability.progress import say

IMPLEMENTER = "implementer"
TRANSPORT = frozenset(("TIMEOUT", "INCOMPLETE", "PROCESS_ERROR"))
TRANSPORT_KEY = "transport"
FORMAT_KEY = "format"
REBUILD_KEY = "rebuild"
CONTEXT_NOTE = "\nTHE PREVIOUS SESSION EXCEEDED THE MODEL CONTEXT WINDOW. This is a new session: use the recorded evidence file instead of repeating research, read only the lines you need (targeted reads of large outputs, never whole logs), and return the next request or the final result as soon as the evidence allows.\n"
OVERFLOW_OUTPUTS = "\nThe session that overflowed received {0} characters of tool output; the largest were: {1}. Do not repeat these calls whole: search their targets or read windows of at most 200 lines.\n"
LARGE_OUTPUT = 10000
NAMED_OUTPUTS = 5
REBUILD_NOTE = "\nPREVIOUS FINAL RESPONSE WAS INVALID: {0}. Fixing it needs source reads that a repair without tools cannot make. Re-read only what you need and return one complete, valid final result or one complete executor request.\n"
# Errors only a pass that can read sources again can fix.
EVIDENCE_ERRORS = (
    "matching observed read",
    "range outside source",
    "reversed line range",
    "Unknown evidence ID",
    "Source claim needs observed evidence",
)


class Retries:
    """Decide whether a failed attempt may run again and what the next attempt gets."""

    def __init__(self, attempts):
        """Restore access recovery history from earlier records of the same stage."""
        self.attempts = attempts
        self.stage = attempts.workflow.flow["stage"]
        self.access = access_recovery.restore(attempts.workflow.state, self.stage)
        self.counts = {TRANSPORT_KEY: 0, FORMAT_KEY: 0, REBUILD_KEY: 0}
        self.repair = {}

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
        if outcome.get("admission_blocked"):
            return False
        status = outcome["status"]
        if status == "INVALID_RESULT":
            return self.format_repair(outcome)
        if status == "BLOCKED_PERMISSION":
            return self.access_recovery(outcome)
        if status == context_overflow.STATUS:
            return self.transport_retry(
                CONTEXT_NOTE,
                overflow_outputs(self.attempts.workflow),
                plan_recovery.feedback(outcome),
            )
        return status in TRANSPORT and self.transport_retry()

    def format_repair(self, outcome):
        """One repair of the response format; edits stay denied, even for the implementer.

        The planner's plan file is fixed with tools instead, in one full attempt.
        """
        if self.counts[FORMAT_KEY] >= 1:
            return False
        self.counts[FORMAT_KEY] += 1
        state = self.attempts.workflow.state
        self.repair = dict(request=self.attempts.request, error=outcome["contract_error"])
        config = self.attempts.workflow.config
        if self.stage == "planner" or needs_sources(outcome["contract_error"], config):
            return full_attempt(self)
        self.attempts.format_only = True
        self.attempts.request = prompts.repair(
            outcome["final_text"],
            outcome["contract_error"],
            role_of(self.stage),
            state.get("contract_version"),
            state["requirements"],
        )
        return True

    def rebuild(self, verdict):
        """A format repair that reports BLOCKED gets one full attempt with tools instead."""
        if not self.attempts.format_only or verdict["status"] != "BLOCKED":
            return False
        if self.counts[REBUILD_KEY]:
            return False
        say("  Format repair could not rebuild the result; one full attempt follows")
        return full_attempt(self)

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

    def transport_retry(self, *notes):
        """Read-only stages retry interrupted transports in a new session with recorded evidence."""
        workflow = self.attempts.workflow
        limit = 0 if self.stage == IMPLEMENTER else workflow.config["read_retries"]
        if self.counts[TRANSPORT_KEY] >= limit or self.access.count:
            return False
        self.counts[TRANSPORT_KEY] += 1
        for note in notes:
            if note not in self.attempts.request:
                self.attempts.request = "{0}{1}".format(self.attempts.request, note)
        if not self.attempts.format_only:
            self.attempts.recovery = evidence.load_index(workflow.run)
        return True


def needs_sources(error, config):
    """An evidence error that a repair without read tools cannot fix."""
    readable = config.get("format_repair_tools") == "read"
    return not readable and any(marker in error for marker in EVIDENCE_ERRORS)


def full_attempt(retries):
    """One attempt with tools and the recorded evidence, given the invalid result's error."""
    attempts = retries.attempts
    retries.counts[REBUILD_KEY] += 1
    attempts.format_only = False
    note = REBUILD_NOTE.format(retries.repair["error"])
    attempts.request = "{0}{1}".format(retries.repair["request"], note)
    attempts.recovery = evidence.load_index(attempts.workflow.run)
    return True


def overflow_outputs(workflow):
    """Name the largest tool outputs of the attempt that just overflowed the context."""
    folder = workflow.run / workflow.state["stages"][-1]["directory"]
    outputs = context_overflow.tool_outputs(folder / "events.jsonl")
    ranked = sorted(outputs, reverse=True)[:NAMED_OUTPUTS]
    largest = [entry for entry in ranked if entry[0] >= LARGE_OUTPUT]
    if not largest:
        return ""
    named = "; ".join("{1} ({0} characters)".format(*entry) for entry in largest)
    return OVERFLOW_OUTPUTS.format(sum(entry[0] for entry in outputs), named)
