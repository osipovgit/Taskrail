"""The `## T<n>` sections of plan.md as plan steps, with their completeness checks.

A task is one action: a single deliverable that one implementation run and one review
can finish, depending on other tasks only through `Depends on`.
"""

import math
import re
from types import MappingProxyType

from countersign.core.plan_markdown import FIELDS, LINE, TASKS
from countersign.core.plan_outcomes import PLACEHOLDER, absolute
from countersign.core.plan_ownership import problems as ownership_problems
from countersign.core.task_graph import order

IDENTIFIER = "id"
NEW_FILE = re.compile(r"\s*\((?:new|new file)\)\s*$", re.IGNORECASE)
NONE_WORDS = frozenset(("", "none", "-", "n/a", "no"))
STEP_FIELDS = MappingProxyType(
    {
        "files": "line {line}: {id} has no Files",
        "criteria": "line {line}: {id} covers no requirement (assign it in ## Requirements)",
        "checks": "line {line}: {id} has no Verify checks",
        "done_when": "line {line}: {id} has no Done when result",
    }
)
REQUIRED = tuple(STEP_FIELDS.items())
TASK_COUNTS = MappingProxyType(
    {
        "split": (2, math.inf, "Decision split needs at least two tasks; use single for one"),
        "single": (1, math.inf, "Decision single needs a task; use no change for none"),
        "none": (0, 0, "Decision no change cannot have tasks"),
    }
)


def steps(document, coverage):
    """Every task section as a plan step, in the plan's order."""
    return [step(task, coverage) for task in document[TASKS]]


def step(task, coverage):
    """One task section."""
    owned = coverage.owners.get(task[IDENTIFIER], [])
    done = listed(task, "done")
    files = [NEW_FILE.sub("", name) for name in listed(task, "files")]
    title = task["title"]
    return dict(
        id=task[IDENTIFIER],
        title=title,
        line=task[LINE],
        action="{0}: {1}".format(title, "; ".join(done) or title),
        files=[str(absolute(name, coverage.roots)) for name in files],
        criteria=list(dict.fromkeys(entry[IDENTIFIER] for entry in owned)),
        scopes=[entry for entry in owned if entry["scope"]],
        depends_on=dependencies(task),
        checks=listed(task, "verify"),
        done_when=done,
        notes=task[FIELDS].get("notes", ("", 0))[0],
    )


def listed(task, key):
    """A list field; files may also be one comma-separated line."""
    entries = task[FIELDS].get(key, ([], 0))[0]
    if key == "files":
        entries = [name.strip() for entry in entries for name in entry.split(",")]
    return [entry for entry in entries if entry and not PLACEHOLDER.match(entry)]


def dependencies(task):
    """Task IDs after `Depends on:`; none is empty."""
    named = task[FIELDS].get("depends", ("", 0))[0]
    if named.strip().casefold() in NONE_WORDS:
        return []
    return [name.upper() for name in re.findall(r"T\d+", named, re.IGNORECASE)]


def check(decision, planned, coverage):
    """Complete tasks, unique ownership, a valid graph and a matching decision."""
    problems = coverage.problems
    known = {entry[IDENTIFIER] for entry in planned}
    if len(known) != len(planned):
        problems.append("Task IDs must be unique")
    unknown = sorted(set(coverage.owners) - known)
    problems.extend(f"## Requirements names {name}, which has no section" for name in unknown)
    problems.extend(incomplete(planned))
    problems.extend(ownership_problems(coverage.owners, coverage.requirements))
    problems.extend(decision_problems(decision, planned))


def incomplete(planned):
    """A problem for every required field a task left empty."""
    found = []
    for entry in planned:
        missing = [text for field, text in REQUIRED if not entry[field]]
        found.extend(text.format(**entry) for text in missing)
    return found


def decision_problems(decision, planned):
    """A dependency cycle or unknown task, and a task count the decision rules out."""
    found = []
    try:
        order(planned)
    except ValueError as error:
        found.append(str(error))
    minimum, maximum, message = TASK_COUNTS.get(decision, (0, math.inf, ""))
    if not minimum <= len(planned) <= maximum:
        found.append(message)
    return found
