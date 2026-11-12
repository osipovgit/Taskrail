"""Shape checks of a local command request before approval."""

import json
import os
import shutil
from pathlib import Path

from taskrail.core import prompt_texts, schema
from taskrail.interactions import local_policy

REQUEST_FIELDS = frozenset(("schema_version", "status", "cwd", "argv", "reason"))
CORE_FIELDS = frozenset(("cwd", "argv"))


def checked_request(payload, roots, writer=True):
    """A canonical cwd inside a declared root and explicit nonempty argument strings.

    An inspecting stage (writer False) may not ask a tool to rewrite files.
    """
    check_cwd(payload.get("cwd"), roots)
    argv = payload["argv"]
    schema.require(schema.valid_argv(argv), "Invalid argv")
    schema.require(
        isinstance(payload["reason"], str) and bool(payload["reason"].strip()),
        "Explain command purpose and effects",
    )
    local_policy.validate(argv)
    if not writer:
        local_policy.read_only(argv)
    return argv


def check_cwd(cwd, roots):
    """A declared root or an existing directory inside one; links cannot leave it."""
    schema.require(isinstance(cwd, str), "cwd must be an absolute path")
    path = Path(cwd)
    schema.require(path.is_absolute(), "cwd must be an absolute path")
    schema.require(
        path.resolve() == path and path.is_dir(), "cwd must be an existing canonical directory"
    )
    inside = any(path.is_relative_to(root) for root in roots.values())
    schema.require(inside, "Use a declared root or a directory inside it as cwd")


def incomplete(payload):
    """A near-miss local request with missing or incorrect routing fields."""
    fields = set(payload)
    if not CORE_FIELDS.issubset(fields) or not fields.issubset(REQUEST_FIELDS):
        return False
    return payload.get("status") != "LOCAL_REQUEST" or "schema_version" not in fields


def correction(payload):
    """Feedback for an incomplete request; nothing was executed."""
    shown = json.dumps(payload, ensure_ascii=False)
    return prompt_texts.text("feedback.incomplete_local", shown=shown)


def executable(argv, cwd, automatic=False):
    """Resolve a relative executable against the requested cwd, just as exec would."""
    program = argv[0]
    if os.path.dirname(program) and not os.path.isabs(program):
        program = os.path.join(cwd, program)
    return shutil.which(program, path=os.defpath if automatic else None)


def missing_executable(argv, automatic=False, *, cwd="."):
    """The program name when it is not installed on the host, else None."""
    return None if executable(argv, cwd, automatic) else argv[0]
