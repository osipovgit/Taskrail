"""The `## T<n>` sections of plan.md as plan steps, with their completeness checks.

A task is one action: a single deliverable that one implementation run and one review
can finish, depending on other tasks only through `Depends on`.
"""

import math
import re
from types import MappingProxyType

from taskrail.core.plan_keys import uncode
from taskrail.core.plan_markdown import FIELDS, LINE, TASKS
from taskrail.core.plan_outcomes import PLACEHOLDER, absolute, cited_ranges
from taskrail.core.plan_ownership import problems as ownership_problems
from taskrail.core.task_graph import order

IDENTIFIER = "id"
NEW_FILE = re.compile(r"\s*\((?:new|new file)\)\s*$", re.IGNORECASE)
NONE_WORDS = frozenset(("", "none", "-", "n/a", "no"))
DEPENDENCY = re.compile(r"(?:T|Task\s*)(\d+)", re.IGNORECASE)
SEPARATOR = re.compile(r"\s*(?:[,;]|\band\b)\s*", re.IGNORECASE)
STEP_FIELDS = MappingProxyType(
    {
        "files": "line {line}: {id} has no Files",
        "criteria": "line {line}: {id} covers no requirement (assign it in ## Requirements)",
        "checks": "line {line}: {id} has no Verify checks",
        "done_when": "line {line}: {id} has no Done when result",
    }
)
REQUIRED = tuple(STEP_FIELDS.items())
EVERYONE_WITHOUT_TASKS = "line {line}: {label} → all tasks needs a task; without tasks give done: <path>:<from>-<to> or gap:"
TASK_COUNTS = MappingProxyType(
    {
        "split": (2, math.inf, "Decision split needs at least two tasks; use single for one"),
        "single": (1, 1, "Decision single needs exactly one task; use split for several"),
        "none": (0, 0, "Decision no change cannot have tasks"),
    }
)


def steps(document, coverage):
    """Every task section as a plan step, in the plan's order."""
    planned = []
    for task in document[TASKS]:
        try:
            planned.append(step(task, coverage))
        except ValueError as error:
            coverage.problems.append(str(error))
    return planned


def step(task, coverage):
    """One task section; requirements of every task belong to each of them."""
    owned = coverage.owners.get(task[IDENTIFIER], []) + coverage.everyone
    done = listed(task, "done")
    files = listed(task, "files")
    title = task["title"]
    return dict(
        id=task[IDENTIFIER],
        title=title,
        line=task[LINE],
        action="{}: {}".format(title, "; ".join(done) or title),
        files=[str(absolute(name, coverage.roots)) for name in files],
        criteria=list(dict.fromkeys(entry[IDENTIFIER] for entry in owned)),
        scopes=[entry for entry in owned if entry.get("scope")],
        depends_on=dependencies(task),
        checks=listed(task, "verify"),
        done_when=done,
        notes=task[FIELDS].get("notes", ("", 0))[0],
        read=cited_ranges(coverage, task[FIELDS].get("read", ([], 0))),
    )


def listed(task, key):
    """A list field; files may also be one comma-separated line."""
    entries = task[FIELDS].get(key, ([], 0))[0]
    if key == "files":
        entries = [name.strip() for entry in entries for name in entry.split(",")]
        entries = map(uncode, (NEW_FILE.sub("", name) for name in entries))
    return [entry for entry in entries if entry and not PLACEHOLDER.match(entry)]


def dependencies(task):
    """Task IDs after `Depends on:`; none is empty."""
    entries, line = task[FIELDS].get("depends", ([], 0))
    named = ", ".join(entries)
    if named.casefold() in NONE_WORDS:
        return []
    parts = [uncode(part.strip()) for part in SEPARATOR.split(named)]
    matches = [DEPENDENCY.fullmatch(part) for part in parts]
    if not all(matches):
        raise ValueError(f"line {line}: invalid Depends on; use task IDs separated by commas")
    return list(dict.fromkeys(f"T{match[1]}" for match in matches))


def check(decision, planned, coverage):
    """Complete tasks, unique ownership, a valid graph and a matching decision."""
    problems = coverage.problems
    if not planned:
        problems.extend(EVERYONE_WITHOUT_TASKS.format(**entry) for entry in coverage.everyone)
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
