"""Requests that only read inside the declared roots run without a personal decision.

Reads and a fixed set of listing and reading commands qualify when every path stays
inside a declared root and away from protected files. Anything else, including an
unknown option, still goes to the operator.
"""

from fnmatch import fnmatch
from pathlib import Path

from countersign.infrastructure.artifact_access import PROTECTED_READ_PATTERNS
from countersign.interactions import access, read_grammar


def request(payload, roots):
    """True for reads, Jenkins reads and listed commands that stay inside the roots."""
    status = payload.get("status")
    if status == "ACCESS_REQUEST":
        return reads(payload["calls"], roots)
    if status == "LOCAL_REQUEST":
        return command(payload, roots)
    return status == "JENKINS_REQUEST"


def command(payload, roots):
    """A listed command whose options are safe and whose paths stay inside the roots."""
    argv = payload["argv"]
    try:
        paths = read_grammar.operands(argv[0], argv[1:])
    except ValueError:
        return False
    cwd = Path(payload["cwd"])
    if not inside(cwd, roots):
        return False
    return all(inside(cwd / path, roots) for path in paths)


def reads(calls, roots):
    """Read and search calls that target canonical paths inside the roots."""
    try:
        paths = [access.target(call, roots) for call in calls]
    except ValueError:
        return False
    return bool(paths) and all(inside(path, roots) for path in paths)


def inside(candidate, roots):
    """A path that resolves inside a declared root and is not a protected file."""
    path = Path(candidate).resolve()
    if any(fnmatch(str(path), pattern) for pattern in PROTECTED_READ_PATTERNS):
        return False
    return any(path.is_relative_to(root) for root in roots.values())
