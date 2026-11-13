"""Task drafts and explicit conversation context for a new planning pass."""

import json
import re

from taskrail.application import run_store, worktree_isolation
from taskrail.core import task_markdown, task_modes, task_spec
from taskrail.core.input_header import HEADER
from taskrail.interactions import approval_policy
from taskrail.web import task_input

HISTORY = "\n## Conversation history\n"
TASK_FILE = "00-input/task.md"
GOAL = "goal"
SUMMARY = "summary"
ANSWER = "answer"
PUBLIC_FIELDS = ("run", "mode", GOAL, SUMMARY, ANSWER)
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
        self.typed = self.read(original)

    @classmethod
    def submitted(cls, run):
        """Read the submitted task separately from the accumulated conversation."""
        original = read_artifact(run, TASK_FILE)
        return cls(original.split(HISTORY, 1)[0])

    def read(self, original):
        """Resolve current structured task fields."""
        return task_spec.resolve(original, task_markdown.typed_input(original, self.metadata))

    def fields(self):
        """The complete typed task fields."""
        return {field["name"]: field["text"] for field in self.typed["fields"]}

    def title(self, fallback):
        """The label displayed for this task."""
        fields = self.fields()
        goal = fields.get(GOAL, "")
        return fields.get("title") or task_input.display_title(goal, fallback)


def task_draft(run, *, editable=False):
    """Reconstruct editable fields from the current task format."""
    index = run_store.read(run)
    parsed = TaskDraft.submitted(run)
    draft = parsed.fields()
    if not editable:
        draft["title"] = parsed.title(run.name)
    draft["read_only"] = parsed.metadata.get("read_only") is True
    draft[DESIGN] = parsed.metadata.get(DESIGN) is True
    draft[DECOMPOSE] = parsed.metadata.get(DECOMPOSE) is True
    draft["verification"] = "\n".join(parsed.metadata.get("verification", []))
    draft["auto_approve"] = approval_policy.at_start(run, parsed.metadata, index)
    draft["roots"] = worktree_isolation.source_roots(index)
    return draft


def saved_turn(run, original):
    """Snapshot public outcomes and the diff, never hidden model context."""
    index = run_store.read(run)
    turn = dict(run=run.name, task=original)
    draft = TaskDraft(original)
    turn[GOAL] = draft.fields()[GOAL]
    turn["mode"] = task_modes.selected(draft.metadata)
    if draft.metadata.get("read_only") or draft.metadata.get(DESIGN):
        key = ANSWER if index.get(ANSWER) else SUMMARY
        return dict(turn, **{key: index.get(key, "")})
    turn["conclusions"] = {
        key: json.loads(read_artifact(run, relative))
        for key, relative in index.get("results", {}).items()
    }
    turn["diff"] = ""
    if (run / "changes.diff").exists():
        turn["diff"] = read_artifact(run, "changes.diff")
    turn[SUMMARY] = index.get(SUMMARY, "")
    return turn


def conversation(run):
    """Carry every turn. Large histories are indexed outside the model prompt."""
    fragments = read_artifact(run, TASK_FILE).split(HISTORY, 1)
    history = []
    if len(fragments) == 2:
        history = json.loads(fragments[1])
    history.append(saved_turn(run, fragments[0]))
    encoded = json.dumps(history, ensure_ascii=False, indent=2)
    return HISTORY + encoded


def previous_messages(run, filename=TASK_FILE):
    """Expose prior conclusions without requiring deleted ancestor artifacts."""
    original = read_artifact(run, filename)
    if HISTORY not in original:
        return []
    return [
        {key: turn[key] for key in PUBLIC_FIELDS if key in turn}
        for turn in json.loads(original.split(HISTORY, 1)[1])
    ]
