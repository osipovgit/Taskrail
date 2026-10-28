"""Commit each approved task on its Taskrail branch, so a task is one reviewed commit.

The commit stages exactly the files the run changed, without hooks, and the guard
adopts the new HEAD before the final checkpoint, so confirmation and the next task of
a split start from it. A failed commit is recorded with its error, never retried.
"""

import json
import textwrap

from taskrail.application.git_state import git_metadata
from taskrail.application.task_branch import BEYOND, KEY
from taskrail.git import process

COMMITS = "commits"
SUBJECT_LIMIT = 72
FALLBACK_IDENTITY = ("user.name=Taskrail", "user.email=taskrail@localhost")


def commit(workflow):
    """Commit an approved task's changes on its branch and checkpoint the new HEAD."""
    if not workflow.config.get(KEY):
        return
    roots = workflow.config["roots"]
    workflow.state[COMMITS] = committed(workflow, commit_message(workflow))
    workflow.guard.adopt(workflow.guard.scan(), git_metadata(roots))
    workflow.checkpoint()


def committed(workflow, message):
    """The new commit of each root with changes, or its error; stops at the first error."""
    heads = []
    changes = grouped(workflow.state.get("changed_files") or [])
    for alias, paths in changes.items():
        try:
            heads.append(
                dict(
                    root=alias, commit=commit_root(workflow.config["roots"][alias], paths, message)
                )
            )
        except ValueError as error:
            heads.append(dict(root=alias, error=str(error)))
            break
    return heads


def grouped(names):
    """Changed names `alias/path`, as paths per root alias."""
    paths = {}
    for name in names:
        alias, relative = name.split("/", 1)
        paths.setdefault(alias, []).append(relative)
    return paths


def commit_message(workflow):
    """The implementer's summary, with the run named in a trailer."""
    path = workflow.run / workflow.state["results"]["implementation"]
    implementation = json.loads(path.read_text(encoding="utf-8"))
    summary = str(implementation.get("summary") or "Taskrail task")
    subject = textwrap.shorten(summary, SUBJECT_LIMIT, placeholder="...")
    run_name = workflow.run.name
    return f"{subject}\n\n{summary}\n\nTaskrail-Run: {run_name}"


def commit_root(root, paths, message):
    """Stage and commit the paths in one repository: the new HEAD, or None if unchanged."""
    process.checked(root, ["add", "--all", "--", *paths])
    if process.invoke(root, ["diff", "--cached", "--quiet"]).returncode == 0:
        return None
    author = process.invoke(root, ["config", "user.email"]).stdout.strip()
    outcome = process.invoke(root, ["commit", "-m", message], () if author else FALLBACK_IDENTITY)
    if outcome.returncode:
        raise ValueError(outcome.stderr.strip() or "git commit failed")
    return process.checked(root, ["rev-parse", "HEAD"]).strip()


def report_lines(state):
    """Commits of approved tasks and files changed beyond the plan on a task branch."""
    commits = [commit_line(entry) for entry in state.get(COMMITS, [])]
    beyond = [f"- {name}" for name in state.get(BEYOND, [])]
    lines = ["", "## Commits", "", *commits] if commits else []
    return [*lines, "", "## Changed beyond the plan", "", *beyond] if beyond else lines


def commit_line(entry):
    """One root's commit, nothing to commit, or the commit error."""
    if "error" in entry:
        return "- {root}: commit failed: {error}".format(**entry)
    return (
        "- {root}: `{commit}`".format(**entry)
        if entry["commit"]
        else "- {root}: nothing to commit".format(**entry)
    )
