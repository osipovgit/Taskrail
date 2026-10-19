"""Shape checks of a local command request before approval."""

import shutil

from countersign.core import schema
from countersign.interactions import local_policy


def checked_request(payload, roots):
    """Require an exact declared cwd and explicit nonempty argument strings."""
    schema.require(
        payload["cwd"] in list(map(str, roots.values())), "Use an exact declared root as cwd"
    )
    argv = payload["argv"]
    schema.require(isinstance(argv, list) and bool(argv), "argv must be a nonempty list")
    schema.require(all(valid_argument(arg) for arg in argv), "Invalid argv")
    schema.require(
        isinstance(payload["reason"], str) and bool(payload["reason"].strip()),
        "Explain command purpose and effects",
    )
    local_policy.validate(argv)
    return argv


def missing_executable(argv):
    """The program name when it is not installed on the host, else None."""
    return None if shutil.which(argv[0]) else argv[0]


def valid_argument(argument):
    """Explicit nonempty strings are passed unchanged to exec."""
    return isinstance(argument, str) and bool(argument) and "\x00" not in argument
