"""Shape checks of a local command request before approval."""

import json
import shutil
from pathlib import Path

from countersign.core import json_response, schema
from countersign.interactions import local_policy

REQUEST_FIELDS = frozenset(("schema_version", "status", "cwd", "argv", "reason"))
CORE_FIELDS = frozenset(("cwd", "argv"))


def checked_request(payload, roots):
    """A canonical cwd inside a declared root and explicit nonempty argument strings."""
    check_cwd(payload["cwd"], roots)
    argv = payload["argv"]
    schema.require(isinstance(argv, list) and bool(argv), "argv must be a nonempty list")
    schema.require(all(valid_argument(arg) for arg in argv), "Invalid argv")
    schema.require(
        isinstance(payload["reason"], str) and bool(payload["reason"].strip()),
        "Explain command purpose and effects",
    )
    local_policy.validate(argv)
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
    return INCOMPLETE.format(shown)


def missing_executable(argv):
    """The program name when it is not installed on the host, else None."""
    return None if shutil.which(argv[0]) else argv[0]


def valid_argument(argument):
    """Explicit nonempty strings are passed unchanged to exec."""
    return isinstance(argument, str) and bool(argument) and "\x00" not in argument


INCOMPLETE = 'Your last response looks like a local command request but is not a complete LOCAL_REQUEST, so nothing was executed: {0}. A request needs "schema_version": 1 and "status": "LOCAL_REQUEST" next to cwd, argv and reason, as the entire response. Resend the complete request, or return your final result.'
