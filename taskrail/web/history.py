"""Task drafts and explicit conversation context for a new planning pass."""

import json
import re

from taskrail.application import worktree_isolation
from taskrail.core import task_markdown, task_spec
from taskrail.core.input_header import HEADER
from taskrail.interactions import approval_policy

HISTORY = "\n## Conversation history\n"
TASK_FILE = "00-input/task.md"
GOAL = "goal"
MAX_HISTORY_BYTES = 256000
DESIGN = "design"
DECOMPOSE = "decompose"


def checked_run(base, name):
    """Resolve a direct run child without following aliases outside storage."""
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("Invalid run ID")
    run = base / name
    if run.is_symlink() or run.resolve().parent != base:
        raise ValueError("Invalid run directory")
    return run


def read_artifact(run, relative):
    """Read only artifacts contained within this run, never external symlinks."""
    path = run / relative
    if run not in path.resolve().parents or path.is_symlink():
        raise ValueError("Artifact must remain within the run")
    return path.read_text(encoding="utf-8")


class TaskDraft:
    """Editable fields of a task file, read like a new task of the same file."""

    def __init__(self, original):
        header = HEADER.search(original)
        self.metadata = json.loads(header[1]) if header else {}
        self.body = original[header.end() :] if header else original
        self.typed = self.read(original)

    def read(self, original):
        """The resolved typed input, or None for an older Markdown file with other sections."""
        try:
            return task_spec.resolve(original, task_markdown.typed_input(original, self.metadata))
        except ValueError:
            if task_spec.TASK_SPEC in self.metadata:
                raise
            return None

    def fields(self):
        """The typed fields; a file the task reader rejects is offered whole as the Goal."""
        if self.typed is not None:
            return {field["name"]: field["text"] for field in self.typed["fields"]}
        return dict(dict.fromkeys(task_spec.FIELDS, ""), goal=self.body.strip())

    def title(self, fallback):
        """The title field, or the first `# ` line of a file the task reader rejects."""
        if self.typed is not None:
            return self.fields().get("title") or fallback
        for line in self.body.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return fallback


def task_draft(run):
    """Reconstruct editable fields and preserve unmapped free-form task text."""
    parsed = TaskDraft(read_artifact(run, TASK_FILE).split(HISTORY, 1)[0])
    draft = parsed.fields()
    draft["title"] = parsed.title(run.name)
    draft["read_only"] = parsed.metadata.get("read_only") is True
    draft["worktree"] = parsed.metadata.get("isolation") != "in_place"
    draft[DESIGN] = parsed.metadata.get(DESIGN) is True
    draft[DECOMPOSE] = parsed.metadata.get(DECOMPOSE) is True
    draft["verification"] = "\n".join(parsed.metadata.get("verification", []))
    index = json.loads(read_artifact(run, "run.json"))
    draft["auto_approve"] = approval_policy.at_start(run, parsed.metadata, index)
    draft["roots"] = worktree_isolation.source_roots(index)
    return draft


def saved_turn(run, original):
    """Snapshot public outcomes and the diff, never hidden model context."""
    index = json.loads(read_artifact(run, "run.json"))
    conclusions = {
        key: json.loads(read_artifact(run, relative))
        for key, relative in index.get("results", {}).items()
    }
    diff = read_artifact(run, "changes.diff") if (run / "changes.diff").exists() else ""
    return dict(
        run=run.name,
        task=original,
        goal=task_draft(run)[GOAL],
        summary=index.get("summary", ""),
        conclusions=conclusions,
        diff=diff,
    )


def conversation(run):
    """Carry bounded history explicitly; fail instead of silently truncating it."""
    fragments = read_artifact(run, TASK_FILE).split(HISTORY, 1)
    history = []
    if len(fragments) == 2:
        history = json.loads(fragments[1])
    history.append(saved_turn(run, fragments[0]))
    encoded = json.dumps(history, ensure_ascii=False, indent=2)
    if len(encoded.encode("utf-8")) > MAX_HISTORY_BYTES:
        raise ValueError("Conversation exceeds 256 KB. Start a new task with a selected summary.")
    return HISTORY + encoded


def previous_messages(run):
    """Expose prior conclusions without requiring deleted ancestor artifacts."""
    original = read_artifact(run, TASK_FILE)
    if HISTORY not in original:
        return []
    return [
        {key: turn.get(key, "") for key in ("run", GOAL, "summary")}
        for turn in json.loads(original.split(HISTORY, 1)[1])
    ]
