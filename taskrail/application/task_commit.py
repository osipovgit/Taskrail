"""Commit each approved task on its Taskrail branch, so a task is one reviewed commit.

The commit stages exactly the files the run changed, without hooks, and the guard
adopts the new HEAD before the final checkpoint, so confirmation and the next task of
a split start from it. A failed commit is recorded with its error, never automatically retried.
"""

import json
import subprocess
import textwrap

from taskrail.application import task_branch
from taskrail.application.artifacts import save_run
from taskrail.application.git_state import git_metadata
from taskrail.application.planned_paths import safe_file
from taskrail.core.schema import require
from taskrail.git import history_outcome, requests, reviewed_commit

COMMITS = "commits"
SUBJECT_LIMIT = 72
FAILURES = (ValueError, OSError, subprocess.SubprocessError)
PENDING = "Commit outcome is uncertain; inspect the Git journal before retrying"


def commit(workflow):
    """Commit an approved task's changes on its branch and checkpoint the new HEAD."""
    if not workflow.config.get(task_branch.KEY):
        return
    completed_status = workflow.state["status"]
    workflow.state.update(status="RUNNING", commits=[])
    if committed(workflow, commit_message(workflow)):
        workflow.state["status"] = completed_status
        workflow.checkpoint()
    save_run(workflow.run, workflow.state)


def committed(workflow, message):
    """The new commit of each root with changes, or its error; stops at the first error."""
    heads = workflow.state[COMMITS]
    changes = grouped(workflow.state.get("changed_files") or [])
    for alias, paths in changes.items():
        entry = dict(root=alias, error=PENDING)
        heads.append(entry)
        save_run(workflow.run, workflow.state)
        try:
            entry["commit"] = commit_root(workflow, alias, paths, message)
        except FAILURES as error:
            entry["error"] = str(error)
            workflow.state.update(status="COMMIT_FAILED", summary=str(error))
            return False
        else:
            entry.pop("error")
        finally:
            workflow.state["git_jobs"] = requests.history(workflow.run)
            save_run(workflow.run, workflow.state)
    return True


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


def commit_root(workflow, alias, paths, message):
    """Accept only the unchanged reviewed source and a verified controlled Git receipt."""
    roots = workflow.config["roots"]
    workflow.guard.verify("Source/Git changed after review")
    require(task_branch.detect(roots, workflow.config["worktrees"]), "No owned task branch")
    files = [safe_file(name, roots) for name in workflow.state["changed_files"]]
    environment = dict(
        run=workflow.run,
        roots=roots,
        allowed_paths=files,
        expected=workflow.guard.expected,
        original_sources=workflow.guard.before,
        scan=workflow.guard.scan,
    )
    revision = reviewed_commit.commit(environment, roots[alias], paths, message)
    metadata = git_metadata(roots)
    if revision:
        require(history_outcome.head(roots[alias]) == revision, "Committed HEAD changed")
    workflow.guard.adopt(workflow.guard.expected, metadata)
    workflow.guard.verify("Source/Git changed during task finalization")
    workflow.checkpoint()
    return revision


def report_lines(state):
    """Commits of approved tasks and files changed beyond the plan on a task branch."""
    commits = [commit_line(entry) for entry in state.get(COMMITS, [])]
    beyond = [f"- {name}" for name in state.get(task_branch.BEYOND, [])]
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
