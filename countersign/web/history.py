"""Task drafts and explicit conversation context for a new planning pass."""

import json
import re
from types import MappingProxyType

from countersign.application import worktree_isolation
from countersign.core import requirements

FIELDS = MappingProxyType(
    {
        "goal": "Goal",
        "criteria": "Acceptance criteria",
        "current_behavior": "Current behavior",
        "entry_points": "Known entry points",
        "constraints": "Additional constraints",
    }
)
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
    """Decode editable sections without discarding user instructions."""

    def __init__(self, original):
        header = re.search(r"(?ms)^```countersign-task\s*\n(.*?)^```\s*$", original)
        self.metadata = json.loads(header[1]) if header else {}
        self.body = original[header.end() :] if header else original
        fragments = re.split(r"(?m)^## ([^\n]+)\n", self.body)
        titles = fragments[1::2]
        paragraphs = fragments[2::2]
        self.sections = dict(zip(titles, paragraphs))
        self.preamble = re.sub(r"(?m)^# [^\n]*\n?", "", fragments[0]).strip()

    def fields(self):
        """Preserve unknown sections as additional constraints."""
        draft = {}
        for key, title in FIELDS.items():
            draft[key] = self.sections.get(title, "").strip()
        draft[GOAL] = draft[GOAL] or self.body.strip()
        draft["criteria"] = draft["criteria"] or "Address the Goal and report verification limits."
        draft["constraints"] = self.constraints(draft["constraints"])
        return draft

    def constraints(self, original):
        """Retain custom rules, including rules from imported task files."""
        paragraphs = [original]
        if self.sections.get("Goal") and self.preamble:
            paragraphs.append(self.preamble)
        for title, section in self.sections.items():
            if title not in {*FIELDS.values(), *requirements.SERVER_TITLES}:
                paragraphs.append(f"### {title}\n{section}")
        return "\n\n".join(paragraphs).strip()

    def title(self, fallback):
        """Find the original title without interpreting its content."""
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
    draft["worktree"] = parsed.metadata.get("isolation") == "worktree"
    draft[DESIGN] = parsed.metadata.get(DESIGN) is True
    draft[DECOMPOSE] = parsed.metadata.get(DECOMPOSE) is True
    draft["auto_approve"] = parsed.metadata.get("auto_approve") is True
    draft["verification"] = "\n".join(parsed.metadata.get("verification", []))
    index = json.loads(read_artifact(run, "run.json"))
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
