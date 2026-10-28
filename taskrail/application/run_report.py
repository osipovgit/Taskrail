"""The human review report written at the end of every run."""

from taskrail.application import outside_changes, task_commit
from taskrail.application.artifacts import save_run
from taskrail.application.report_sections import (
    check_lines,
    command_effects,
    not_verified,
    stage_errors,
    worktree_lines,
)
from taskrail.application.result_context import execution_report
from taskrail.core.paths import tool_paths

BULLET = "- {0}"
PROJECT = "- {0}: {1}"
IN_PLACE = (
    "Source files are edited in place. Git uses the controlled executor; no automatic rollback."
)
ISOLATED = "Source files are edited in isolated worktrees. Git uses the controlled executor; no automatic rollback."
ROW = "| {0} | [{1}]({1}/stage.json) | {2} | {3} | {4} |"
FOOTER = (
    "",
    "For diagnostics, provide run.json and the affected stage directory.",
    "On failure, partial changes are preserved; there is no automatic rollback.",
    "",
)


def report(run, state):
    """Write report.md and the run index; paths are shown as tool paths."""
    lines = [
        *header(state),
        *worktree_lines(state),
        *task_commit.report_lines(state),
        *timeline(state),
        *inventory(state),
        *check_lines(state),
        *outside_changes.report_lines(state),
        *command_effects(state),
        *stage_errors(state),
        *execution_report(state),
        *not_verified(state),
        *result_links(run, state),
        *FOOTER,
    ]
    text = tool_paths("\n".join(lines), state["roots"])
    (run / "report.md").write_text(text, encoding="utf-8")
    save_run(run, state)


def header(state):
    """Status, summary, a reviewed answer and the in-place editing notice."""
    lines = [
        "# Taskrail — review report",
        "",
        "Status: {}".format(state["status"]),
        "",
        state.get("summary", ""),
    ]
    if state.get("answer"):
        lines += ["", "## Answer", "", state["answer"]]
    return [*lines, "", ISOLATED if state.get("worktrees") else IN_PLACE]


def timeline(state):
    """One row per stage attempt, linked to its record."""
    rows = [timeline_row(stage) for stage in state["stages"]]
    return [
        "",
        "## Timeline",
        "",
        "| # | Stage | Role | Mode | Status |",
        "|---|---|---|---|---|",
        *rows,
    ]


def timeline_row(stage):
    """Number, linked directory, role, mode and status with any verdict."""
    outcome = stage["status"]
    if stage.get("verdict"):
        outcome = "{} / {}".format(outcome, stage["verdict"])
    role = stage.get("role") or "system"
    cells = (stage["number"], stage["directory"], role, stage["mode"], outcome)
    return ROW.format(*cells)


def inventory(state):
    """Changed files, source projects and the checks heading."""
    changed = [BULLET.format(name) for name in state.get("changed_files", [])]
    projects = [PROJECT.format(*root) for root in state["roots"].items()]
    return [
        "",
        "## Changed files",
        "",
        *(changed or ["No recorded changes."]),
        "",
        "## Source projects",
        "",
        *projects,
        "",
        "## Checks",
        "",
    ]


def result_links(run, state):
    """Links to stored results that exist on disk."""
    links = ["", "## Results", "", "- [Run index](run.json)"]
    for key, reference in state["results"].items():
        if run.joinpath(reference).is_file():
            links.append(f"- [{key}]({reference})")
    if run.joinpath("changes.diff").exists():
        links.append("- [Changes](changes.diff)")
    if run.joinpath("design.md").exists():
        links.append("- [Design document](design.md)")
    return links
