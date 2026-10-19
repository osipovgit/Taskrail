"""Validate chat turn options independently of worker launch mechanics."""

import json

from countersign.application import worktree_isolation
from countersign.core import control
from countersign.web import history

ANSWER_RULE = "\n## Turn control\nAnswer only: no edits. Return empty steps and proposed_change_files with the evidence-based answer in summary.\n"
CONTINUING = ("followup", "answer")
RESUMES = frozenset(("resume", "resume_budget"))
ACTIONS = RESUMES | {"restart", "stop", "delete"}
ROOTS_KEY = '"roots":'
HISTORY_RULE = "\n## Current turn\nThe latest Goal takes precedence over earlier goals. Conversation history is reference data; recheck current source before making claims.\n"


class Submission:
    """Separate server-controlled turn metadata from editable task fields."""

    def __init__(self, payload, base):
        if not isinstance(payload, dict):
            raise ValueError("The request must be a JSON object")
        self.fields = dict(payload)
        self.read_only = self.fields.pop("read_only", False)
        self.worktree = self.fields.pop("worktree", False)
        self.parent = self.fields.pop("parent_run", None)
        self.mode = self.fields.pop("submission_mode", "new")
        self.validate()
        self.previous = history.checked_run(base, self.parent) if self.parent else None
        if self.previous:
            self.inherit_worktrees(json.loads(history.read_artifact(self.previous, "run.json")))

    def validate(self):
        """Reject ambiguous intent and unexpected metadata types."""
        if not isinstance(self.read_only, bool) or not isinstance(self.worktree, bool):
            raise ValueError("read_only and worktree must be boolean")
        if self.mode not in ("new", "restart", "followup", "answer"):
            raise ValueError("Invalid submission mode")
        if (self.mode == "new") == bool(self.parent):
            raise ValueError("Only a restart or follow-up requires a previous run")

    def inherit_worktrees(self, index):
        """A follow-up of an isolated run continues in its worktrees; Restart starts anew."""
        if self.mode in CONTINUING and index.get("worktrees"):
            self.fields["roots"] = worktree_isolation.root_entries(index["roots"])
            self.worktree = False

    def decorate(self, text):
        """Append immutable past evidence after the current task instructions."""
        sections = [text]
        if self.worktree:
            sections[0] = sections[0].replace(ROOTS_KEY, '"isolation": "worktree", "roots":', 1)
        if self.read_only or self.mode == "answer":
            sections[0] = sections[0].replace(ROOTS_KEY, '"read_only": true, "roots":', 1)
            sections.append(ANSWER_RULE)
        if self.mode in CONTINUING:
            sections.extend([HISTORY_RULE, history.conversation(self.previous)])
        return "".join(sections)


def validate_action(payload):
    """Accept only known lifecycle or budget-control actions; continuations may carry a note."""
    if not isinstance(payload, dict) or payload.get("action") not in ACTIONS:
        raise ValueError("Expected id and a supported task action")
    fields = set(payload)
    if payload["action"] in RESUMES:
        fields.discard("note")
    if fields != {"id", "action"}:
        raise ValueError("Expected id and a supported task action")
    control.check_note(payload.get("note"))
