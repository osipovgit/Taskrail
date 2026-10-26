"""The browser's task fields, built from CLI options."""

import json
import sys
from pathlib import Path
from types import MappingProxyType

FIELDS = ("title", "goal", "criteria", "current_behavior", "entry_points", "constraints")
ANSWER = "answer"
DESIGN = "design"
MODES = MappingProxyType(
    {
        "develop": {},
        ANSWER: {"read_only": True},
        DESIGN: {DESIGN: True},
        "split": {"decompose": True},
    }
)
TURNS = MappingProxyType({ANSWER: ANSWER, DESIGN: DESIGN})


def task_payload(args):
    """The fields of POST /api/tasks from a JSON document or the options."""
    if args.payload:
        return json.loads(read_payload(args.payload))
    named = [field for field in (*FIELDS, "verification") if getattr(args, field)]
    payload = {field: field_text(getattr(args, field)) for field in named}
    payload["roots"] = [root_entry(entry) for entry in args.root]
    payload.update(MODES[args.mode])
    if args.allow_all:
        payload["auto_approve"] = True
    if args.worktree:
        payload["worktree"] = True
    return dict(payload, **turn(args))


def read_payload(source):
    """A JSON document from a file, or from standard input for -."""
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8")


def turn(args):
    """A follow-up or restart names the earlier run; a new task names none."""
    if args.followup and args.restart:
        raise ValueError("Use either --followup or --restart")
    if args.followup:
        return dict(parent_run=args.followup, submission_mode=TURNS.get(args.mode, "followup"))
    if args.restart:
        return dict(parent_run=args.restart, submission_mode="restart")
    return {}


def field_text(option):
    """Option text, or the contents of the file named after @."""
    if option.startswith("@"):
        return Path(option[1:]).expanduser().read_text(encoding="utf-8")
    return option


def root_entry(option):
    """ALIAS=PATH as a form root."""
    alias, separator, path = option.partition("=")
    if not separator or not alias or not path:
        raise ValueError(f"Expected --root ALIAS=PATH, got {option}")
    return dict(alias=alias, path=path)
