"""Validate chat turn options independently of worker launch mechanics."""

import json
import re
from types import MappingProxyType

from taskrail.application import check_parents, child_inputs, worktree_isolation
from taskrail.core import control, delivery_record, prompt_texts, schema, task_spec
from taskrail.web import history, restarts, task_form

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
TASK = "task"
SCOPE = "task_scope"
ASSIGNED_CONTRACT = "assigned_contract"
ASSIGNED_REQUIREMENTS = "assigned_requirements"
CHECK_SPECS = "check_specs"
CONTEXT = "context"
# The run whose confirmed change a server check run checks.
CHANGE = "confirmed_change"
# A split's task run, Jenkins validation and the server checks after confirmation.
PHASES = frozenset(("", TASK, "integration", "validation", "server"))
CHECK_PHASES = frozenset(("integration", "validation", "server"))
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
            "integration_review",
        )
    )
    | TASK_ACTIONS
)
TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
ACTIONS = RESUMES | RECORDED | {"restart", "stop", "delete"}
ROOTS_KEY = '"roots":'


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
        self.delivery = {CONTEXT: context, PHASE: self.fields.pop(PHASE, "")}
        self.delivery[CHANGE] = self.fields.pop(CHANGE, "")
        self.delivery["parent_context"] = child_inputs.checked(
            self.fields.pop("parent_context", "")
        )
        self.delivery[SCOPE] = self.fields.pop(SCOPE, None)
        self.delivery[ASSIGNED_CONTRACT] = self.fields.pop(ASSIGNED_CONTRACT, None)
        self.delivery[ASSIGNED_REQUIREMENTS] = task_spec.checked_assignments(
            self.fields.pop(ASSIGNED_REQUIREMENTS, [])
        )
        self.delivery[CHECK_SPECS] = self.fields.pop(CHECK_SPECS, [])
        self.delivery[check_parents.PARENT] = self.fields.pop(check_parents.PARENT, None)
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
        check_scope(self.delivery)
        check_assignment(self.delivery)

    def check_phase(self):
        """A server-set delivery phase; checks after a change never edit files."""
        phase = self.delivery[PHASE]
        if phase not in PHASES:
            raise ValueError("Unknown delivery phase")
        self.flags[READ_ONLY] = self.flags[READ_ONLY] or phase in CHECK_PHASES
        check_parents.reference(self.delivery)
        change = self.delivery[CHANGE]
        if change and (phase != "server" or not delivery_record.RUN_NAME.fullmatch(change)):
            raise ValueError("Only a server check names the confirmed change it checks")

    def check_decompose(self):
        """Splitting into tasks plans later code changes, so it starts a new conversation."""
        if not self.flags[DECOMPOSE]:
            return
        if self.flags[READ_ONLY] or self.flags[DESIGN] or self.mode in CONTINUING:
            raise ValueError("Split into tasks is a separate mode for a new or restarted task")

    def inherit_worktrees(self, index):
        """A follow-up of an isolated run continues in its worktrees; Restart starts anew."""
        restarts.require_standalone(self.previous, self.mode, index)
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
        for name in (PHASE, CHANGE, check_parents.PARENT):
            if self.delivery[name]:
                options.append(f'"{name}": "{self.delivery[name]}"')
        if self.delivery[SCOPE] is not None:
            options.append(f'"task_scope": {json.dumps(self.delivery[SCOPE])}')
        if self.delivery[ASSIGNED_CONTRACT] is not None:
            options.append(f'"assigned_contract": {json.dumps(self.delivery[ASSIGNED_CONTRACT])}')
        if self.delivery[CHECK_SPECS]:
            options.append(f'"check_specs": {json.dumps(self.delivery[CHECK_SPECS])}')
        header = ", ".join([*options, ROOTS_KEY])
        sections = [text.replace(ROOTS_KEY, header, 1)]
        sections[0] = assign_requirements(sections[0], self.delivery)
        if self.delivery[CONTEXT]:
            sections.append(f"\n## Task split context\n{self.delivery[CONTEXT]}\n")
        if self.mode in CONTINUING:
            sections.extend(
                [prompt_texts.current("task.history"), history.conversation(self.previous)]
            )
        return "".join(sections)


def split_context(text):
    """Server-written context of one task of a split goal: bounded text, no reserved blocks."""
    context = task_form.field_text(dict(split_context=text), "split_context")
    task_form.check_reserved([context])
    return context


def check_task(payload):
    """The task ID a split action names; returns the field name."""
    task = payload.get(TASK)
    if not isinstance(task, str) or not TASK_ID.fullmatch(task):
        raise ValueError("Expected the ID of a task of the split")
    return TASK


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


def check_scope(delivery):
    """Only a child task carries the parent's reviewed file boundary."""
    scope = delivery[SCOPE]
    valid = delivery[PHASE] == TASK and isinstance(scope, list)
    if scope is not None and not valid:
        raise ValueError("task_scope is only a list on a task phase")


def check_assignment(delivery):
    """A child's claimed lineage is validated against the real parent before execution."""
    contract = delivery[ASSIGNED_CONTRACT]
    if contract is None:
        allowed = not delivery[ASSIGNED_REQUIREMENTS] or delivery[PHASE] in CHECK_PHASES
        schema.require(allowed, "Assigned requirements need a parent contract")
        return
    valid = delivery[PHASE] == TASK and isinstance(contract, dict)
    schema.require(valid, "Invalid assigned parent contract")
    schema.require(set(contract) == {"parent_run", "task_id"}, "Invalid assigned parent fields")
    parent = contract["parent_run"]
    task = contract["task_id"]
    schema.require(
        isinstance(parent, str) and bool(delivery_record.RUN_NAME.fullmatch(parent)),
        "Invalid assigned parent run",
    )
    schema.require(
        isinstance(task, str) and bool(TASK_ID.fullmatch(task)), "Invalid assigned task ID"
    )


def assign_requirements(text, delivery):
    """Keep child inputs structured; displayed Markdown is an artifact, not a parser input."""
    if not delivery[ASSIGNED_REQUIREMENTS] and not delivery[CONTEXT]:
        return text
    start, encoded = text.split("\n", 1)
    header, rest = encoded.split("\n```", 1)
    meta = json.loads(header)
    meta["task_spec"][ASSIGNED_REQUIREMENTS] = delivery[ASSIGNED_REQUIREMENTS]
    meta["task_spec"][CONTEXT] = delivery[CONTEXT]
    return f"{start}\n{json.dumps(meta, ensure_ascii=False, indent=2)}\n```{rest}"
