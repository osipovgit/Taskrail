"""Validate chat turn options independently of worker launch mechanics."""

import json
from types import MappingProxyType

from countersign.application import worktree_isolation
from countersign.core import control
from countersign.web import history

ANSWER_RULE = "\n## Turn control\nAnswer only: no edits. Return empty steps and proposed_change_files with the evidence-based answer in summary.\n"
DESIGN = "design"
DESIGN_RULE = "\n## Turn control\nDesign discussion: no edits. Return empty steps and proposed_change_files. In summary write a design document in Markdown with the sections Context, Options, Trade-offs, Recommendation, Risks, Implementation outline and Open questions, grounded in quoted source evidence. In a continued discussion, refine the earlier document according to the latest Goal.\n"
CONTINUING = ("followup", "answer", DESIGN)
MODES = ("new", "restart", *CONTINUING)
READ_ONLY = "read_only"
WORKTREE = "worktree"
AUTO_APPROVE = "auto_approve"
DECOMPOSE = "decompose"
DECOMPOSE_RULE = "\n## Turn control\nSplit into tasks: plan the whole Goal as 2 to 8 sequential tasks; nothing is edited in this run. Each plan step is one task that a later, separate run plans again and implements on its own. Write its action as '<short title>: <what the task delivers>', list the files it changes, the requirement IDs it covers as criteria, the earlier tasks it needs in depends_on and its acceptance checks. Keep every task small enough for one focused review (a few hundred changed lines, about ten files). Order tasks so each leaves the project working.\n"
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
RECORDED = frozenset(
    ("done", "reopen", "revoke_auto_approve", "epic_next", "epic_auto_on", "epic_auto_off")
)
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
        self.check_decompose()

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
        """Server-owned header options and turn rules, then immutable past evidence."""
        options = [HEADER_OPTIONS[flag] for flag in FLAGS if self.flags[flag]]
        if self.flags[DESIGN] and not self.flags[READ_ONLY]:
            options.append(HEADER_OPTIONS[READ_ONLY])
        header = ", ".join([*options, ROOTS_KEY])
        sections = [text.replace(ROOTS_KEY, header, 1)]
        if self.flags[DECOMPOSE]:
            sections.append(DECOMPOSE_RULE)
        elif self.flags[DESIGN]:
            sections.append(DESIGN_RULE)
        elif self.flags[READ_ONLY]:
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
