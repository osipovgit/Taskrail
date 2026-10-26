"""Task Markdown from a validated browser form; no client-controlled commands or settings."""

import json
from pathlib import Path
from types import MappingProxyType

from taskrail.core import input_header
from taskrail.web import history, task_input
from taskrail.web.form_roots import checked_roots

TITLE = "title"
GOAL = "goal"
CRITERIA = "criteria"
CONSTRAINTS = "constraints"
FIELDS = (
    TITLE,
    GOAL,
    CRITERIA,
    "current_behavior",
    "entry_points",
    CONSTRAINTS,
    "verification",
)
DEFAULT_CRITERIA = (
    "The Goal is achieved; the report states what was verified and what remains unverified."
)
TITLE_WORDS = 80
FIELD_LIMIT = 16000
TITLE_LIMIT = 160
FENCE = input_header.FENCE
SECTIONS = MappingProxyType(
    {
        GOAL: "Goal",
        "current_behavior": "Current behavior",
        CRITERIA: "Acceptance criteria",
        "entry_points": "Known entry points",
        CONSTRAINTS: "Additional constraints",
    }
)
WORKFLOW_RULES = (
    "",
    "## Workflow rules",
    "Discover related files and the minimal change scope within the declared roots.",
    "Preserve unrelated changes. Use controlled Git access; never hard-reset, clean, rewrite history or force-push. Do not edit Git metadata directly.",
    "Use English for generated explanations, comments, documentation and reports.",
    "The server runs syntax checks and configured verification commands. Report all unexecuted checks as unverified.",
    "Remote actions require the isolated SSH executor and personal approval of exact scripts and targets.",
)


def build_task(payload, runs):
    """Return (task Markdown, title) for a validated form."""
    if not isinstance(payload, dict):
        raise ValueError("The request must be a JSON object")
    if set(payload) - set(FIELDS) - {"roots"}:
        raise ValueError("Unknown task fields; commands and settings cannot be submitted")
    form = form_text(payload)
    roots = checked_roots(payload.get("roots"), Path(runs).resolve())
    meta = task_input.metadata(payload, form, roots, task_markdown(form, ""))
    header = json.dumps(meta, ensure_ascii=False, indent=2)
    return task_markdown(form, header), form[TITLE]


def form_text(payload):
    """Stripped text fields; only the goal is required, title and criteria have defaults."""
    form = {key: field_text(payload, key) for key in FIELDS}
    if not form[GOAL]:
        raise ValueError("Required field: goal")
    form[TITLE] = form[TITLE] or default_title(form[GOAL])
    form[CRITERIA] = form[CRITERIA] or DEFAULT_CRITERIA
    check_title(form[TITLE])
    check_reserved(form.values())
    return form


def default_title(goal):
    """The goal's first line, shortened at a word boundary."""
    line = goal.splitlines()[0].strip()
    if len(line) <= TITLE_WORDS:
        return line
    return "{}...".format(line[:TITLE_WORDS].rsplit(" ", 1)[0])


def check_title(title):
    """A single line of bounded length."""
    if len(title) > TITLE_LIMIT or "\n" in title or "\r" in title:
        raise ValueError("Title must be one line, at most 160 characters")


def check_reserved(texts):
    """The server owns the task header and the conversation history."""
    texts = list(texts)
    if any(FENCE.search(text) for text in texts):
        raise ValueError("The form generates the taskrail-task header; do not embed another one")
    if any(history.HISTORY.strip() in text for text in texts):
        raise ValueError("Conversation history is reserved for server-generated context")


def field_text(payload, key):
    """One bounded text field."""
    text = payload.get(key, "")
    if not isinstance(text, str) or "\x00" in text:
        raise ValueError(f"Invalid or oversized field: {key}")
    if len(text) > FIELD_LIMIT:
        raise ValueError(f"Invalid or oversized field: {key}")
    return text.strip()


def task_markdown(form, header):
    """The taskrail-task header, the form sections and fixed workflow rules."""
    sections = ["```taskrail-task", header, "```", "", f"# {form[TITLE]}"]
    for field, heading in SECTIONS.items():
        if form[field]:
            sections.extend(["", f"## {heading}", form[field]])
    return "{}\n".format("\n".join([*sections, *WORKFLOW_RULES]))
