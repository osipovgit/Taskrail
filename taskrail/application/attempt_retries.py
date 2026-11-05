"""Progress-aware handoff and transport recovery for one stage."""

from taskrail.application import context_handoff, evidence, feedback_files, plan_recovery
from taskrail.core import prompt_texts
from taskrail.infrastructure import context_overflow

IMPLEMENTER = "implementer"
TRANSPORT = frozenset(("LAUNCH_ERROR", "INCOMPLETE", "PROCESS_ERROR", "TURN_ERROR"))
CONTRACT_ERROR = "contract_error"
LARGE_OUTPUT = 10000
NAMED_OUTPUTS = 5


class Retries:
    """Decide whether a failed attempt may run again and what the next attempt gets."""

    def __init__(self, attempts):
        """Track bounded context and result recovery for the current stage."""
        self.attempts = attempts
        self.stage = attempts.workflow.flow["stage"]
        self.crashes = 0
        self.original = attempts.request
        self.repair = False
        self.handoffs = set()

    def mode(self):
        """The record mode of the next attempt."""
        if self.attempts.recovery:
            return "research-recovery"
        return "model"

    def allowed(self, outcome):
        """Return True after preparing the next attempt, False to stop the stage."""
        status = outcome["status"]
        if status in TRANSPORT:
            if self.crashes >= self.attempts.workflow.config["transport_retries"]:
                return False
            self.crashes += 1
        elif status not in {"INVALID_RESULT", "NO_PROGRESS", context_overflow.STATUS}:
            return False
        return self.handoff(outcome)

    def handoff(self, outcome):
        """Carry the work into a fresh session once per distinct failure and work state."""
        workflow = self.attempts.workflow
        status = outcome["status"]
        reason = outcome.get(CONTRACT_ERROR) or outcome.get("errors", [])
        signature = (status, str(reason), context_handoff.signature(workflow))
        # Context diagnostics contain changing token counts; occupancy alone is not progress.
        if status == context_overflow.STATUS:
            signature = (status, signature[-1])
        if signature in self.handoffs and status not in TRANSPORT:
            return False
        self.handoffs.add(signature)
        self.repair = status == "INVALID_RESULT"
        self.attempts.request = self.original + note(self.guidance(outcome, reason))
        self.attempts.recovery = evidence.load_index(workflow.run)
        return True

    def guidance(self, outcome, reason):
        """Return the handoff route and only the current unresolved work."""
        workflow = self.attempts.workflow
        status = outcome["status"]
        notes = [prompt_texts.text("recovery.strategy")]
        if status == context_overflow.STATUS:
            notes.extend(context_notes(self, outcome))
        elif reason:
            folder = workflow.run / workflow.state["stages"][-1]["directory"]
            notes.append(
                prompt_texts.text(
                    "recovery.rebuild", error=feedback_files.validation(folder, str(reason))
                )
            )
        if self.stage == IMPLEMENTER:
            notes.append(prompt_texts.text("note.interrupted_writer"))
        return "\n".join(notes)


def context_notes(retries, outcome):
    """What a fresh session after a full context needs: a writer, its notes and edits."""
    workflow = retries.attempts.workflow
    if retries.stage != IMPLEMENTER:
        context = note(prompt_texts.text("recovery.context"))
        folder = workflow.run / workflow.state["stages"][-1]["directory"]
        return [context, overflow_outputs(workflow), plan_recovery.feedback(outcome, folder)]
    changed = context_handoff.changed_paths(workflow, workflow.state["changed_files"])
    handoff = prompt_texts.text("recovery.handoff", files=changed)
    return [note(handoff), overflow_outputs(workflow)]


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
