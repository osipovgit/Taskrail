"""Bound recovery input and recognize unchanged work across context rollovers."""

import json

from taskrail.core import prompt_texts
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
    payload = dict(source=workflow.guard.expected, notes=notes)
    return digest(json.dumps(payload, sort_keys=True).encode())


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
