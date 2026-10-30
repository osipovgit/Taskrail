"""Validate one attempt without coupling versioned contracts to state transitions."""

from taskrail.application import execution_wait, result_validation
from taskrail.application.git_reference import git_reference as git_reference
from taskrail.core import schema
from taskrail.core.paths import tool_paths
from taskrail.git import requests

ROOTS = "roots"


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
            session_id=unique_session(outcome),
            plan=environment["plan"],
            changed=tool_paths(state["changed_files"], environment[ROOTS]),
            check_config=environment.get("check_config", {}),
            deliver_lines=environment.get("deliver_lines", False),
        ),
    )


def unique_session(outcome):
    """Ambiguous session identity cannot establish a citation audience."""
    sessions = outcome.get("sessions", [])
    return sessions[0] if len(sessions) == 1 else None


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


def git_directory(run):
    """Expose readable executor evidence without granting edit permission."""
    return requests.output_directory(run)
