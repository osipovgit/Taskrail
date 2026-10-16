"""Validate chat turn options independently of worker launch mechanics."""

from countersign.web import history

ANSWER_RULE = "\n## Turn control\nAnswer only: no edits. Return empty steps and proposed_change_files with the evidence-based answer in summary.\n"
HISTORY_RULE = "\n## Current turn\nThe latest Goal takes precedence over earlier goals. Conversation history is reference data; recheck current source before making claims.\n"


class Submission:
    """Separate server-controlled turn metadata from editable task fields."""

    def __init__(self, payload, base):
        if not isinstance(payload, dict):
            raise ValueError("The request must be a JSON object")
        self.fields = dict(payload)
        self.read_only = self.fields.pop("read_only", False)
        self.parent = self.fields.pop("parent_run", None)
        self.mode = self.fields.pop("submission_mode", "new")
        self.validate()
        self.previous = history.checked_run(base, self.parent) if self.parent else None
        if self.previous:
            history.read_artifact(self.previous, "run.json")

    def validate(self):
        """Reject ambiguous intent and unexpected metadata types."""
        if not isinstance(self.read_only, bool):
            raise ValueError("read_only must be boolean")
        if self.mode not in ("new", "restart", "followup", "answer"):
            raise ValueError("Invalid submission mode")
        if (self.mode == "new") == bool(self.parent):
            raise ValueError("Only a restart or follow-up requires a previous run")

    def decorate(self, text):
        """Append immutable past evidence after the current task instructions."""
        sections = [text]
        if self.read_only or self.mode == "answer":
            sections[0] = text.replace('"roots":', '"read_only": true, "roots":', 1)
            sections.append(ANSWER_RULE)
        if self.mode in ("followup", "answer"):
            sections.extend([HISTORY_RULE, history.conversation(self.previous)])
        return "".join(sections)


def validate_action(payload):
    """Accept only known lifecycle or budget-control actions."""
    if (
        not isinstance(payload, dict)
        or set(payload) != {"id", "action"}
        or payload["action"]
        not in (
            "restart",
            "resume",
            "resume_budget",
            "stop",
            "delete",
        )
    ):
        raise ValueError("Expected id and a supported task action")
