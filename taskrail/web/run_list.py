"""The run list: started runs and launches that have not created a run yet."""

from operator import itemgetter

from taskrail.application import run_store
from taskrail.core import task_modes
from taskrail.web import (
    delivery_state,
    discussions,
    history,
    lifecycle,
    run_errors,
    run_family,
    run_groups,
)
from taskrail.web.run_files import contained, read_json
from taskrail.web.run_sources import launch_record

SUMMARY_LIMIT = 500
RUN_INDEX = "run.json"
REQUIRED_LAUNCH_FIELDS = frozenset(("title", "status"))


def list_runs(base):
    """Newest first by run ID."""
    if not base.is_dir():
        return []
    entries = [entry for entry in map(run_entry, base.iterdir()) if entry]
    entries.extend(pending_entries(base, {entry["id"] for entry in entries}))
    by_id = {entry["id"]: entry for entry in entries}
    for root, links in discussions.replies_by_root(base).items():
        if root in by_id:
            group_card(by_id, root, discussions.chain(root, links)[1:])
    return sorted(by_id.values(), key=itemgetter("id"), reverse=True)


def group_card(by_id, root, names):
    """A missing or removed member never hides a surviving run."""
    members = [name for name in names if name in by_id]
    if members:
        latest = members[-1]
        related = list(by_id[root].get("members", []))
        for name in members:
            related.extend(by_id[name].get("members", []))
        current = by_id[latest]
        for name in members:
            by_id.pop(name)
        by_id[root] = dict(
            current,
            id=root,
            title=by_id[root]["title"],
            latest=latest,
            members=members,
            related=related,
        )


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
        mode=task_modes.selected(draft.metadata),
        group=run_groups.group(path, state, status),
        summary=state.get("summary", "")[:SUMMARY_LIMIT],
    )
    summary.update(delivery_state.list_fields(path, state, summary["group"]))
    summary.update(run_family.member_fields(path))
    return summary


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
    launch = launch_record(folder)
    if not isinstance(launch, dict) or not REQUIRED_LAUNCH_FIELDS.issubset(launch):
        return None
    if launch.get("resume"):
        return None
    try:
        metadata = run_family.task_metadata(folder, "task.md")
    except run_errors.ERRORS:
        return None
    if run_family.visible_parent(folder.parent.parent, metadata):
        return None
    entry = dict(id=folder.name, summary=launch.get("summary", ""))
    entry.update(title=launch["title"], status=launch["status"])
    entry["mode"] = task_modes.selected(metadata)
    entry["group"] = run_groups.group(folder, {}, launch["status"])
    return entry
