"""Shared source boundaries for citations, repair delivery and readable views."""

from pathlib import Path

from taskrail.application import dependency_checks
from taskrail.core import schema


def roots(run, path, declared):
    """Run-owned evidence never inherits access from an overlapping project root."""
    if run not in path.parents:
        return declared
    return {
        name: run / "00-input" / name
        for name in ("git", "ssh", "local", "checks", "preimages", "original", "dependency-checks")
    }


def verify_dependencies(context, claims):
    """Historical receipts only substantiate claims with an intact child-local seal."""
    run = context["run"]
    directory = run / dependency_checks.DIRECTORY
    cited = (Path(claim["path"]) for claim in claims)
    if any(directory in path.parents for path in cited):
        spec = context.get("check_config", {}).get("task_spec", {})
        schema.require(dependency_checks.index(run, spec), "Unauthenticated dependency checks")
