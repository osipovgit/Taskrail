"""Bound recovery input and recognize unchanged work across context rollovers."""

import json

from taskrail.application import evidence
from taskrail.core import prompt_texts, source_lines
from taskrail.core.files import digest
from taskrail.core.paths import tool_paths

PATH_BYTES = 4000


def signature(workflow):
    """Repeated overflow without changed source or working notes cannot make progress."""
    files = ("plan.md", "review.md", "progress.md")
    notes = {
        name: digest(workflow.run.joinpath(name).read_bytes())
        for name in files
        if workflow.run.joinpath(name).is_file()
    }
    payload = (workflow.guard.expected, notes, research(workflow.run))
    return digest(json.dumps(payload, sort_keys=True).encode())


def research(run):
    """Compare observed source versions and windows independently of attempt/session IDs."""
    sources = {}
    for record in evidence.validation_records(run):
        source = (record["input"]["filePath"], record["source_sha256"])
        lines = source_lines.returned_lines(record)
        if lines:
            sources.setdefault(source, set()).update(lines)
    return [(source, source_lines.windows(sources[source])) for source in sorted(sources)]


def work_version(workflow):
    """A changed plan or project merits review even when some findings survive."""
    if workflow.flow["stage"] == "plan-reviewer":
        return digest((workflow.run / "plan.md").read_bytes())
    return digest(json.dumps(workflow.guard.expected, sort_keys=True).encode())


def changed_paths(workflow, names):
    """Bound the handoff inventory independently of changed path count and length."""
    chosen = []
    size = 0
    for name in tool_paths(names, workflow.config["roots"]):
        size += len(name.encode()) + 2
        if size > PATH_BYTES:
            break
        chosen.append(name)
    summary = ", ".join(chosen) or "none"
    omitted = len(names) - len(chosen)
    if omitted:
        summary = "{}\n{}".format(
            summary,
            prompt_texts.text(
                "recovery.changed_omitted", count=omitted, path=workflow.run / "changes.diff"
            ),
        )
    return summary


def prior_handoff(stages, run):
    """Offer the interrupted stage its public notes on rollover or explicit Continue."""
    if len(stages) < 2:
        return ""
    previous, current = stages[-2:]
    saved = run / previous["directory"] / "handoff.md"
    if previous["stage"] == current["stage"] and saved.is_file():
        return "\n{}".format(prompt_texts.text("recovery.saved", path=saved))
    return ""
