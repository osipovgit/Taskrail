"""The run list: started runs and launches that have not created a run yet."""

import contextlib
from operator import itemgetter
from types import MappingProxyType

from taskrail.application import run_store
from taskrail.web import (
    answer_threads,
    delivery_state,
    history,
    lifecycle,
    run_errors,
    run_family,
    run_groups,
)
from taskrail.web.run_files import contained, read_json

SUMMARY_LIMIT = 500
RUN_INDEX = "run.json"
REQUIRED_LAUNCH_FIELDS = frozenset(("title", "status"))
# Header flags in precedence order: a design discussion is also read-only.
MODES = MappingProxyType(
    {history.DECOMPOSE: history.DECOMPOSE, history.DESIGN: history.DESIGN, "read_only": "answer"}
)


def list_runs(base):
    """Newest first by run ID."""
    if not base.is_dir():
        return []
    entries = [entry for entry in map(run_entry, base.iterdir()) if entry]
    entries.extend(pending_entries(base, {entry["id"] for entry in entries}))
    return sorted(answer_threads.cards(base, entries), key=itemgetter("id"), reverse=True)


def run_entry(path):
    """A readable run directory, or None; a task or phase run is shown in its parent."""
    if path.name.startswith(".") or path.is_symlink() or not path.is_dir():
        return None
    try:
        return run_summary(path)
    except run_errors.ERRORS as error:
        return run_errors.summary(path, error) if path.joinpath(RUN_INDEX).is_file() else None


def run_summary(path):
    """ID, title, display status and a bounded summary."""
    state = read_json(contained(path, RUN_INDEX))
    if not run_store.supported(state):
        return None
    draft = history.TaskDraft.submitted(path)
    if run_family.visible_parent(path.parent, draft.metadata):
        return None
    status = lifecycle.display_status(path, state)
    summary = dict(
        id=path.name,
        title=draft.title(path.name),
        status=status,
        mode=task_mode(draft.metadata),
        group=run_groups.group(path, state, status),
        summary=state.get("summary", "")[:SUMMARY_LIMIT],
    )
    summary.update(delivery_state.list_fields(path, state, summary["group"]))
    summary.update(run_family.member_fields(path))
    return summary


def task_mode(metadata):
    """develop, answer, design or decompose, from the server-generated task header."""
    for flag, mode in MODES.items():
        if metadata.get(flag) is True:
            return mode
    return "develop"


def pending_entries(base, known):
    """Launches without a run directory; continuation launches are not listed."""
    submissions = base / ".submissions"
    if not submissions.is_dir() or submissions.is_symlink():
        return []
    folders = [
        folder
        for folder in submissions.iterdir()
        if folder.name not in known and not (base / folder.name / RUN_INDEX).exists()
    ]
    return [entry for entry in map(pending_entry, folders) if entry]


def pending_entry(folder):
    """A readable launch record of a new run, or None."""
    if folder.is_symlink() or not folder.is_dir():
        return None
    try:
        launch = read_json(contained(folder, "launch.json"))
    except run_errors.ERRORS:
        return None
    # A continuation, task or phase launch is shown in its own or its parent's card.
    shown_elsewhere = True
    with contextlib.suppress(*run_errors.ERRORS):
        metadata = run_family.task_metadata(folder, "task.md")
        shown_elsewhere = run_family.visible_parent(folder.parent.parent, metadata)
    if not isinstance(launch, dict) or launch.get("resume") or shown_elsewhere:
        return None
    if not REQUIRED_LAUNCH_FIELDS.issubset(launch):
        return None
    entry = dict(id=folder.name, summary=launch.get("summary", ""))
    entry.update(title=launch["title"], status=launch["status"])
    entry["group"] = run_groups.group(folder, {}, launch["status"])
    return entry
