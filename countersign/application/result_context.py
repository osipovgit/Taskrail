"""Validate one attempt without coupling versioned contracts to state transitions."""

from countersign.application import execution_wait, result_validation
from countersign.core import schema
from countersign.core.paths import tool_paths
from countersign.git import requests

ROOTS = "roots"
GIT_DIRECTORY = ".git"


def parse(outcome, record, state, environment):
    """Validate only the supported contract; do not normalize old result shapes."""
    schema.contract_version(state.get("contract_version"))
    return result_validation.validate(
        outcome["final_text"],
        dict(
            role=record["role"],
            stage=record["stage"],
            requirements=state["requirements"],
            roots=environment[ROOTS],
            run=environment["run"],
            folder=environment["run"] / record["directory"],
            plan=environment["plan"],
            changed=tool_paths(state["changed_files"], environment[ROOTS]),
        ),
    )


def execution_context(run, state):
    """Return the durable execution history after any pending approval."""
    return execution_wait.resume(run, state) + requests.context(run)


def execution_report(state):
    """Include executor outcomes without treating them as blanket acceptance."""
    lines = execution_wait.report_lines(state)
    if state.get("git_jobs"):
        lines += [
            "",
            "## Git execution",
            "",
            "Requests: [git-execution.json](git-execution.json)",
            "",
        ]
        for entry in state["git_jobs"]:
            lines.append("- {stage}: {status}".format(**entry))
    return lines


def fingerprints(state, expected, git_before):
    """Adopt only the scope-checked executor result on the next attempt."""
    return state.pop("git_effect", (expected, git_before))


def git_directory(run):
    """Expose readable executor evidence without granting edit permission."""
    return requests.output_directory(run)


def git_reference(root):
    """Guard Git metadata even when a declared root is a repository subdirectory."""
    if (root / GIT_DIRECTORY).exists():
        return root / GIT_DIRECTORY
    for parent in root.parents:
        if (parent / GIT_DIRECTORY).exists():
            return parent / GIT_DIRECTORY
    return root / GIT_DIRECTORY
