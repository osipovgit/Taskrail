"""Shape checks of a local command request before approval."""

import json
import os
import shutil
from pathlib import Path

from countersign.core import json_response, prompt_texts, schema
from countersign.interactions import local_policy

REQUEST_FIELDS = frozenset(("schema_version", "status", "cwd", "argv", "reason"))
CORE_FIELDS = frozenset(("cwd", "argv"))


def checked_request(payload, roots, writer=True):
    """A canonical cwd inside a declared root and explicit nonempty argument strings.

    An inspecting stage (writer False) may not ask a tool to rewrite files.
    """
    check_cwd(payload["cwd"], roots)
    argv = payload["argv"]
    schema.require(isinstance(argv, list) and bool(argv), "argv must be a nonempty list")
    schema.require(all(valid_argument(arg) for arg in argv), "Invalid argv")
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


def incomplete(text):
    """A response that looks like a LOCAL_REQUEST but lacks its status or schema_version."""
    try:
        payload = json_response.extract(text, dict)
    except ValueError:
        return False
    fields = set(payload)
    if not CORE_FIELDS.issubset(fields) or not fields.issubset(REQUEST_FIELDS):
        return False
    return payload.get("status") != "LOCAL_REQUEST" or "schema_version" not in fields


def correction(text):
    """Feedback for an incomplete request; nothing was executed."""
    shown = json.dumps(json_response.extract(text, dict), ensure_ascii=False)
    return prompt_texts.text("feedback.incomplete_local", shown=shown)


def missing_executable(argv, automatic=False):
    """The program name when it is not installed on the host, else None."""
    search_path = os.defpath if automatic else None
    return None if shutil.which(argv[0], path=search_path) else argv[0]


def valid_argument(argument):
    """Explicit nonempty strings are passed unchanged to exec."""
    return isinstance(argument, str) and bool(argument) and "\x00" not in argument
