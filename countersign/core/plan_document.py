"""Turn plan.md into the plan result the workflow validates and stores.

The planner writes decisions only; the server derives the coverage, evidence,
blocking gaps, steps and change files, and reports every problem with its line.
"""

from types import MappingProxyType

from countersign.core import plan_checks
from countersign.core.plan_markdown import (
    AFTER,
    ANSWER,
    PROBLEMS,
    REQUIREMENTS,
    TOP,
    read_plan_text,
)
from countersign.core.plan_outcomes import PLACEHOLDER, PLANNED, Coverage
from countersign.core.plan_tasks import check, steps

NONE = "none"
DECISIONS = MappingProxyType(
    {
        "split": "split",
        "single": "single",
        "blocked": "blocked",
        "no change": NONE,
        "no-change": NONE,
        NONE: NONE,
    }
)
PROBLEM_LIMIT = 12
BLOCKED = "blocked"


def payload(text, requirements, roots):
    """The plan result of plan.md, or ValueError naming every problem by line."""
    document = read_plan_text(text)
    coverage = Coverage(requirements, roots)
    coverage.problems.extend(document[PROBLEMS])
    decision = read_decision(document, coverage.problems)
    coverage.read(document[REQUIREMENTS])
    planned = steps(document, coverage)
    if decision != BLOCKED:
        check(decision, planned, coverage)
    coverage.found["unverified"].extend(after_checks(document))
    if decision == BLOCKED:
        planned = blocked(coverage.found, top_text(document))
    report(coverage.problems, coverage.found, decision)
    selected = plan_checks.selections(document[plan_checks.SELECTIONS], requirements)
    if selected:
        coverage.found[plan_checks.SELECTIONS] = selected
    return finished(coverage.found, decision, top_text(document), planned)


def after_checks(document):
    """The checks listed under `## After the change`."""
    checks = [text for text, _ in document[AFTER]]
    return list(filter(None, checks))


def finished(found, decision, summary, planned):
    """The plan result in the stored shape; files_read is filled from observed reads."""
    names = [name for entry in planned for name in entry["files"]]
    files = list(dict.fromkeys(names))
    status = "BLOCKED" if decision == BLOCKED else "PLAN_READY"
    plan = dict(found, schema_version=1, status=status, decision=decision)
    plan.update(summary=summary or "No summary", steps=planned)
    return dict(plan, files_read=[], proposed_change_files=files)


def read_decision(document, problems):
    """split, single, none or blocked; None after a problem."""
    written, line = document[TOP].get("decision", ("", 0))
    decision = DECISIONS.get(written.strip().casefold())
    if decision is None:
        where = f"line {line}" if line else "Decision"
        problems.append(f"{where}: Decision must be split, single, no change or blocked")
    return decision


def blocked(found, summary):
    """A blocked plan authorizes nothing; its planned requirements wait with it."""
    for entry in found["coverage"]:
        if entry["outcome"] == PLANNED:
            entry["outcome"] = "not_evaluated"
    if not found["blocking_gaps"]:
        found["blocking_gaps"].append(summary or "The plan is blocked")
    return []


def top_text(document):
    """The answer section, else the summary, without a template placeholder."""
    answer = "\n".join(document[ANSWER]).strip()
    summary = document[TOP].get("summary", ("", 0))[0]
    if answer:
        return answer
    return "" if PLACEHOLDER.match(summary) else summary


def report(problems, found, decision):
    """All problems at once, so one correction can fix them."""
    if found["blocking_gaps"] and decision not in {None, BLOCKED}:
        problems.append("A requirement is a gap: set Decision: blocked, or plan the work")
    if problems:
        raise ValueError("plan.md: {}".format("; ".join(problems[:PROBLEM_LIMIT])))
