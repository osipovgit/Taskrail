"""Bounded retry policy of one stage: format repair, access and transport recovery."""

from taskrail.application import access_recovery, evidence, plan_recovery, prompts
from taskrail.core import prompt_texts
from taskrail.infrastructure import context_overflow
from taskrail.observability.progress import say

IMPLEMENTER = "implementer"
TRANSPORT = frozenset(("TIMEOUT", "INCOMPLETE", "PROCESS_ERROR"))
TRANSPORT_KEY = "transport"
FORMAT_KEY = "format"
REBUILD_KEY = "rebuild"
CONTRACT_ERROR = "contract_error"
LARGE_OUTPUT = 10000
NAMED_OUTPUTS = 5
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
        if final(self.stage, outcome, self.attempts.workflow.config):
            return False
        status = outcome["status"]
        if status == "INVALID_RESULT":
            return self.format_repair(outcome)
        if status == "BLOCKED_PERMISSION":
            return self.access_recovery(outcome)
        if status == context_overflow.STATUS:
            return self.transport_retry(
                note(prompt_texts.text("recovery.context")),
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
        self.repair = dict(request=self.attempts.request, error=outcome[CONTRACT_ERROR])
        config = self.attempts.workflow.config
        if self.stage == "planner" or needs_sources(outcome[CONTRACT_ERROR], config):
            return full_attempt(self)
        self.attempts.format_only = True
        self.attempts.request = prompts.repair(
            outcome["final_text"],
            outcome[CONTRACT_ERROR],
            self.stage,
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
        self.attempts.request += correction
        count = self.access.count
        say(f"  Access denied; continuing with allowed sources ({count}/2)")
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
                self.attempts.request += note
        if not self.attempts.format_only:
            self.attempts.recovery = evidence.load_index(workflow.run)
        return True


def final(stage, outcome, config):
    """An outcome no retry should repeat: blocked admission, a planner error already
    returned for repair, or, when stop_on_provider_limit is set, a provider limit."""
    if outcome.get("provider_limit") and config.get("stop_on_provider_limit"):
        say("  Provider quota or billing limit reached; no retry until it resets")
        return True
    repaired = stage == "planner" and outcome["status"] == "INVALID_RESULT"
    repaired = repaired and outcome.get(CONTRACT_ERROR) in outcome.get("validation_errors", [])
    return bool(outcome.get("admission_blocked")) or repaired


def needs_sources(error, config):
    """An evidence error that a repair without read tools cannot fix."""
    readable = config.get("format_repair_tools") == "read"
    return not readable and any(marker in error for marker in EVIDENCE_ERRORS)


def full_attempt(retries):
    """One attempt with tools and the recorded evidence, given the invalid result's error."""
    attempts = retries.attempts
    retries.counts[REBUILD_KEY] += 1
    attempts.format_only = False
    rebuild = note(prompt_texts.text("recovery.rebuild", error=retries.repair["error"]))
    attempts.request = "{}{}".format(retries.repair["request"], rebuild)
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
    return note(
        prompt_texts.text("recovery.overflow", total=sum(map(output_size, outputs)), named=named)
    )


def output_size(entry):
    """Characters of one recorded tool output."""
    return entry[0]


def note(text):
    """A note appended to the request on a line of its own."""
    return f"\n{text}\n"
