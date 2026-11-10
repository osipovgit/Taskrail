"""Shared source boundaries for citations, repair delivery and readable views."""

from pathlib import Path

from taskrail.application import dependency_checks, plan_reports, report_packets
from taskrail.core import schema


def roots(run, path, declared):
    """Run-owned evidence never inherits access from an overlapping project root."""
    if run not in path.parents:
        return declared
    return {
        name: run / "00-input" / name
        for name in (
            "git",
            "remote",
            "local",
            "checks",
            "preimages",
            "original",
            "dependency-checks",
            "plan-reports",
        )
    }


def verify_dependencies(context, claims):
    """Historical receipts only substantiate claims with an intact child-local seal."""
    run = context["run"]
    directory = run / dependency_checks.DIRECTORY
    cited = [Path(claim["path"]) for claim in claims]
    spec = context.get("check_config", {}).get("task_spec", {})
    reports = run / plan_reports.DIRECTORY
    if any(reports in path.parents for path in cited):
        report_packets.verified(reports, spec.get(plan_reports.SIGNATURE))
    if any(directory in path.parents for path in cited):
        schema.require(dependency_checks.index(run, spec), "Unauthenticated dependency checks")
