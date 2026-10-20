"""The run list: started runs and launches that have not created a run yet."""

from operator import itemgetter
from types import MappingProxyType

from countersign.web import delivery_state, history, lifecycle, run_groups
from countersign.web.run_files import contained, read_json

SUMMARY_LIMIT = 500
TITLE_PREFIX = "# "
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
    return sorted(entries, key=itemgetter("id"), reverse=True)


def run_entry(path):
    """A readable run directory, or None."""
    if path.is_symlink() or not path.is_dir():
        return None
    try:
        return run_summary(path)
    except (OSError, ValueError, AttributeError):
        return None


def run_summary(path):
    """ID, title, display status and a bounded summary."""
    state = read_json(contained(path, "run.json"))
    task = history.read_artifact(path, history.TASK_FILE)
    request = task.split(history.HISTORY, 1)[0]
    status = lifecycle.display_status(path, state)
    summary = dict(
        id=path.name,
        title=task_title(request, path.name),
        status=status,
        mode=task_mode(request),
        group=run_groups.group(path, state, status),
        summary=state.get("summary", "")[:SUMMARY_LIMIT],
    )
    summary.update(delivery_state.list_fields(path, state, summary["group"]))
    return summary


def task_mode(task):
    """change, answer, design or decompose, from the server-generated task header."""
    metadata = history.TaskDraft(task).metadata
    for flag, mode in MODES.items():
        if metadata.get(flag) is True:
            return mode
    return "change"


def task_title(task, fallback):
    """The first Markdown level-one heading."""
    for line in task.splitlines():
        if line.startswith(TITLE_PREFIX):
            return line.lstrip(TITLE_PREFIX).strip()
    return fallback


def pending_entries(base, known):
    """Launches without a run directory; continuation launches are not listed."""
    submissions = base / ".submissions"
    if not submissions.is_dir() or submissions.is_symlink():
        return []
    folders = [folder for folder in submissions.iterdir() if folder.name not in known]
    return [entry for entry in map(pending_entry, folders) if entry]


def pending_entry(folder):
    """A readable launch record of a new run, or None."""
    if folder.is_symlink() or not folder.is_dir():
        return None
    try:
        launch = read_json(contained(folder, "launch.json"))
    except (OSError, ValueError):
        return None
    if not isinstance(launch, dict) or launch.get("resume"):
        return None
    if not REQUIRED_LAUNCH_FIELDS.issubset(launch):
        return None
    entry = dict(id=folder.name, summary=launch.get("summary", ""))
    entry.update(title=launch["title"], status=launch["status"])
    entry["group"] = run_groups.group(folder, {}, launch["status"])
    return entry
