"""Requests that only read inside the declared roots run without a personal decision.

Reads and a fixed set of listing and reading commands qualify when every path stays
inside a declared root and away from protected files. Anything else, including an
unknown option, still goes to the operator.
"""

from pathlib import Path

from taskrail.core import protected_paths
from taskrail.interactions import read_grammar


def request(payload, roots, protected=protected_paths.DEFAULT_PATTERNS):
    """True for reads, Jenkins reads and listed commands that stay inside the roots."""
    status = payload.get("status")
    scope = (roots, protected)
    if status == "LOCAL_REQUEST":
        return command(payload, *scope)
    return status == "JENKINS_REQUEST"


def command(payload, roots, protected=protected_paths.DEFAULT_PATTERNS):
    """A listed command whose options are safe and whose paths stay inside the roots."""
    argv = payload["argv"]
    try:
        paths = read_grammar.operands(argv[0], argv[1:])
    except ValueError:
        return False
    cwd = Path(payload["cwd"])
    if not inside(cwd, roots, protected):
        return False
    return all(inside(cwd / path, roots, protected) for path in paths)


def inside(candidate, roots, protected):
    """A path that resolves inside a declared root and is not a protected file."""
    path = Path(candidate).resolve()
    if protected_paths.matches(path, protected):
        return False
    return any(path.is_relative_to(root) for root in roots.values())
