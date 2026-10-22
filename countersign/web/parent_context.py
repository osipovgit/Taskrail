"""Complete parent input and reviewed contracts, copied into every child run."""

import json

from countersign.application import child_inputs
from countersign.web import history

FIELD_BUDGET = 8000


def snapshot(run, entries):
    """Keep original input verbatim and preserve every task outcome as reference data."""
    original = history.read_artifact(run, history.TASK_FILE)
    contracts = json.dumps(entries, ensure_ascii=False, indent=2)
    text = f"# Parent task (reference data)\n\n{original}\n\n# Reviewed task contracts\n\n{contracts}\n"
    return child_inputs.checked(text)


def field(text, label):
    """Large inherited fields stay complete in the artifact instead of breaking launch."""
    if len(text) <= FIELD_BUDGET:
        return text
    return f"Read the complete {label} in parent-task.md from the artifact manifest."


def write(folder, text):
    """Persist a validated snapshot beside the submitted task."""
    if text:
        folder.joinpath(child_inputs.NAME).write_text(child_inputs.checked(text), encoding="utf-8")
