"""Freeze reports selected by a reviewed step and project them into its own run."""

import re
from pathlib import Path

from taskrail.application import report_packets, report_sources
from taskrail.core import prompt_texts, protected_paths, read_hints, schema

DIRECTORY = "00-input/plan-reports"
SIGNATURE = "plan_reports_sha256"
STORE = "plan-report-packets"


def bind(plan, context, *, verify=False):
    """Bind selected reports to the planner result before independent review."""
    config = context.get("check_config", {})
    if plan.get("decision") != "split" and not config.get("decompose"):
        return
    run = context["run"]
    protected = protected_paths.patterns(config)
    for step in plan.get("steps", []):
        paths = report_sources.selected(run, step.get("read", []), protected)
        _bind_step(step, paths, run / STORE, verify)


def _bind_step(step, paths, store, verify):
    signature = report_packets.signature(paths)
    if verify:
        message = prompt_texts.text("validation.split_report_changed", step=step["id"])
        schema.require(signature == step.get(SIGNATURE), message)
    elif signature:
        files = {report_packets.qualified(path): path for path in paths}
        report_packets.publish(store / signature, files, signature)
        step[SIGNATURE] = signature


def inherit(run, step, parent):
    """Publish the approved step's own immutable packet and rewrite its read pointers."""
    signature = step.get(SIGNATURE)
    if signature is None:
        _require_portable(step.get("read", []), parent)
        return step
    source = parent / STORE / signature
    schema.require(re.fullmatch(r"[0-9a-f]{64}", signature), "Invalid plan report signature")
    report_packets.verified(source, signature)
    destination = run / DIRECTORY
    report_packets.publish(destination, {path.name: path for path in source.iterdir()}, signature)
    hints = [portable(hint, parent, destination) for hint in step["read"]]
    return dict(step, read=report_packets.with_companions(hints, destination))


def portable(hint, parent, destination):
    """The local copy has unchanged bytes, so any supplied inclusive range survives."""
    name, suffix = read_hints.split_hint(hint)
    path = Path(name)
    if report_sources.executor_path(parent, path):
        return str(destination / report_packets.qualified(path)) + suffix
    return hint


def _require_portable(hints, parent):
    names = (read_hints.split_hint(hint)[0] for hint in hints)
    missing = any(report_sources.executor_path(parent, Path(name)) for name in names)
    schema.require(not missing, "Missing reviewed report packet; replan the parent task")
