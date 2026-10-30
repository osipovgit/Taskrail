"""Bounded retry policy of one stage: a full attempt for an invalid result, access and
transport recovery."""

from taskrail.application import access_recovery, context_handoff, evidence, plan_recovery
from taskrail.core import prompt_texts
from taskrail.infrastructure import context_overflow
from taskrail.observability.progress import say

IMPLEMENTER = "implementer"
TRANSPORT = frozenset(("TIMEOUT", "INCOMPLETE", "PROCESS_ERROR"))
TRANSPORT_KEY = "transport"
RESULT_KEY = "result"
CONTRACT_ERROR = "contract_error"
LARGE_OUTPUT = 10000
NAMED_OUTPUTS = 5
# Errors only a pass that can read sources again can fix.


class Retries:
    """Decide whether a failed attempt may run again and what the next attempt gets."""

    def __init__(self, attempts):
        """Restore access recovery history from earlier records of the same stage."""
        self.attempts = attempts
        self.stage = attempts.workflow.flow["stage"]
        self.access = access_recovery.restore(attempts.workflow.state, self.stage)
        self.counts = {TRANSPORT_KEY: 0, RESULT_KEY: 0}
        self.repair = {}
        self.handoffs = set()

    def mode(self):
        """The record mode of the next attempt."""
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
            return self.result_repair(outcome)
        if status == "BLOCKED_PERMISSION":
            return self.access_recovery(outcome)
        if status == context_overflow.STATUS:
            return self.handoff(outcome)
        return status in TRANSPORT and self.transport_retry()

    def handoff(self, outcome):
        """Do not spend another fresh session repeating an unchanged context failure."""
        signature = context_handoff.signature(self.attempts.workflow)
        if signature in self.handoffs:
            return False
        self.handoffs.add(signature)
        return self.transport_retry(*context_notes(self, outcome), handoff=True)

    def result_repair(self, outcome):
        """One full attempt with tools corrects the plan or review file.

        The implementer's final word was already corrected in its session; it gets none.
        """
        if self.counts[RESULT_KEY] >= 1 or self.stage == IMPLEMENTER:
            return False
        self.counts[RESULT_KEY] += 1
        self.repair = dict(request=self.attempts.request, error=outcome[CONTRACT_ERROR])
        return full_attempt(self)

    def access_recovery(self, outcome):
        """Continue a read-only stage with allowed sources after a new denial."""
        workflow = self.attempts.workflow
        if self.stage == IMPLEMENTER:
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

    def transport_retry(self, *notes, handoff=False):
        """Read-only stages retry interrupted transports in a new session with recorded evidence.

        A writer that filled its context hands off to a fresh session the same way; it
        is never retried after any other interruption.
        """
        workflow = self.attempts.workflow
        limit = workflow.config["read_retries"]
        if self.stage == IMPLEMENTER and not handoff:
            limit = 0
        if self.counts[TRANSPORT_KEY] >= limit or self.access.count:
            return False
        self.counts[TRANSPORT_KEY] += 1
        for note in notes:
            if note not in self.attempts.request:
                self.attempts.request += note
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


def full_attempt(retries):
    """One attempt with tools and the recorded evidence, given the invalid result's error."""
    attempts = retries.attempts
    rebuild = note(prompt_texts.text("recovery.rebuild", error=retries.repair["error"]))
    attempts.request = "{}{}".format(retries.repair["request"], rebuild)
    attempts.recovery = evidence.load_index(attempts.workflow.run)
    return True


def context_notes(retries, outcome):
    """What a fresh session after a full context needs: a writer, its notes and edits."""
    workflow = retries.attempts.workflow
    if retries.stage != IMPLEMENTER:
        context = note(prompt_texts.text("recovery.context"))
        return context, overflow_outputs(workflow), plan_recovery.feedback(outcome)
    names = workflow.state.get("changed_files") or []
    changed = context_handoff.changed_paths(workflow, names)
    handoff = prompt_texts.text("recovery.handoff", files=changed)
    return note(handoff), overflow_outputs(workflow)


def overflow_outputs(workflow):
    """Name the largest tool outputs of the attempt that just overflowed the context."""
    folder = workflow.run / workflow.state["stages"][-1]["directory"]
    events = folder / "events.jsonl"
    total, largest = context_overflow.largest_outputs(events, NAMED_OUTPUTS, LARGE_OUTPUT)
    if not largest:
        return ""
    named = "; ".join("{1} ({0} characters)".format(*entry) for entry in largest)
    return note(prompt_texts.text("recovery.overflow", total=total, named=named))


def note(text):
    """A note appended to the request on a line of its own."""
    return f"\n{text}\n"
