"""Validate chat turn options independently of worker launch mechanics."""

import json
import re
from types import MappingProxyType

from countersign.application import worktree_isolation
from countersign.core import control
from countersign.web import history, task_form

DESIGN = "design"
CONTINUING = ("followup", "answer", DESIGN)
MODES = ("new", "restart", *CONTINUING)
READ_ONLY = "read_only"
WORKTREE = "worktree"
AUTO_APPROVE = "auto_approve"
DECOMPOSE = "decompose"
FLAGS = (READ_ONLY, WORKTREE, DESIGN, AUTO_APPROVE, DECOMPOSE)
HEADER_OPTIONS = MappingProxyType(
    {
        READ_ONLY: '"read_only": true',
        WORKTREE: '"isolation": "worktree"',
        DESIGN: '"design": true',
        AUTO_APPROVE: '"auto_approve": true',
        DECOMPOSE: '"decompose": true',
    }
)
RESUMES = frozenset(("resume", "resume_budget"))
ACTION = "action"
PHASE = "phase"
# A split's task run, Jenkins validation and the server checks after confirmation.
PHASES = frozenset(("", "task", "validation", "server"))
CHECK_PHASES = frozenset(("validation", "server"))
TASK_ACTIONS = frozenset(("epic_pause", "epic_unpause"))
RECORDED = (
    frozenset(
        (
            "done",
            "reopen",
            "revoke_auto_approve",
            "epic_next",
            "epic_auto_on",
            "epic_auto_off",
            "confirm",
        )
    )
    | TASK_ACTIONS
)
TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
ACTIONS = RESUMES | RECORDED | {"restart", "stop", "delete"}
ROOTS_KEY = '"roots":'
HISTORY_RULE = "\n## Current turn\nThe latest Goal takes precedence over earlier goals. Conversation history is reference data; recheck current source before making claims.\n"


class Submission:
    """Separate server-controlled turn metadata from editable task fields."""

    def __init__(self, payload, base):
        """Pop the turn options; the remaining fields form the task."""
        if not isinstance(payload, dict):
            raise ValueError("The request must be a JSON object")
        self.fields = dict(payload)
        self.flags = {flag: self.fields.pop(flag, False) for flag in FLAGS}
        self.parent = self.fields.pop("parent_run", None)
        self.mode = self.fields.pop("submission_mode", "new")
        context = split_context(self.fields.pop("split_context", ""))
        self.delivery = {"context": context, PHASE: self.fields.pop(PHASE, "")}
        self.validate()
        self.previous = history.checked_run(base, self.parent) if self.parent else None
        if self.previous:
            self.inherit_worktrees(json.loads(history.read_artifact(self.previous, "run.json")))

    @property
    def worktree(self):
        """Run in new isolated worktrees."""
        return self.flags[WORKTREE]

    def validate(self):
        """Reject ambiguous intent and unexpected metadata types."""
        if not all(isinstance(flag, bool) for flag in self.flags.values()):
            raise ValueError(
                "read_only, worktree, design, auto_approve and decompose must be boolean"
            )
        if self.mode not in MODES:
            raise ValueError("Invalid submission mode")
        if (self.mode == "new") == bool(self.parent):
            raise ValueError("Only a restart or follow-up requires a previous run")
        self.flags[DESIGN] = self.flags[DESIGN] or self.mode == DESIGN
        self.flags[READ_ONLY] = self.flags[READ_ONLY] or self.mode == "answer"
        self.check_phase()
        self.check_decompose()

    def check_phase(self):
        """A server-set delivery phase; checks after a change never edit files."""
        phase = self.delivery[PHASE]
        if phase not in PHASES:
            raise ValueError("Unknown delivery phase")
        self.flags[READ_ONLY] = self.flags[READ_ONLY] or phase in CHECK_PHASES

    def check_decompose(self):
        """Splitting into tasks plans later code changes, so it starts a new conversation."""
        if not self.flags[DECOMPOSE]:
            return
        if self.flags[READ_ONLY] or self.flags[DESIGN] or self.mode in CONTINUING:
            raise ValueError("Split into tasks is a separate mode for a new or restarted task")

    def inherit_worktrees(self, index):
        """A follow-up of an isolated run continues in its worktrees; Restart starts anew."""
        if self.mode in CONTINUING and index.get("worktrees"):
            self.fields["roots"] = worktree_isolation.root_entries(index["roots"])
            self.flags[WORKTREE] = False

    def decorate(self, text):
        """Server-owned header options, task split context, then immutable past evidence.

        The mode's instructions come from the header flags at prompt time (mode_rules).
        """
        options = [HEADER_OPTIONS[flag] for flag in FLAGS if self.flags[flag]]
        if self.flags[DESIGN] and not self.flags[READ_ONLY]:
            options.append(HEADER_OPTIONS[READ_ONLY])
        if self.delivery[PHASE]:
            options.append('"phase": "{0}"'.format(self.delivery[PHASE]))
        header = ", ".join([*options, ROOTS_KEY])
        sections = [text.replace(ROOTS_KEY, header, 1)]
        if self.delivery["context"]:
            sections.append("\n## Task split context\n{0}\n".format(self.delivery["context"]))
        if self.mode in CONTINUING:
            sections.extend([HISTORY_RULE, history.conversation(self.previous)])
        return "".join(sections)


def split_context(text):
    """Server-written context of one task of a split goal: bounded text, no reserved blocks."""
    context = task_form.field_text(dict(split_context=text), "split_context")
    task_form.check_reserved([context])
    return context


def check_task(payload):
    """The task ID a split action names; returns the field name."""
    task = payload.get("task")
    if not isinstance(task, str) or not TASK_ID.fullmatch(task):
        raise ValueError("Expected the ID of a task of the split")
    return "task"


def validate_action(payload):
    """Accept only known lifecycle or budget-control actions; continuations may carry a note."""
    if not isinstance(payload, dict) or payload.get(ACTION) not in ACTIONS:
        raise ValueError("Expected id and a supported task action")
    fields = set(payload)
    if payload[ACTION] in RESUMES:
        fields.discard("note")
    if payload[ACTION] in TASK_ACTIONS:
        fields.discard(check_task(payload))
    if fields != {"id", ACTION}:
        raise ValueError("Expected id and a supported task action")
    control.check_note(payload.get("note"))
