"""Validate one attempt without coupling versioned contracts to state transitions."""

from taskrail.application import (
    execution_wait,
    implementation_submission,
    plan_feedback,
    result_validation,
    run_store,
)
from taskrail.application.git_reference import git_reference as git_reference
from taskrail.application.plan_review_evidence import paths as plan_paths
from taskrail.core.paths import tool_paths
from taskrail.git import requests

ROOTS = "roots"


def parse(outcome, record, state, environment):
    """Validate only the supported contract; do not normalize old result shapes."""
    run = environment["run"]
    run_store.validate(state)
    return result_validation.validate(
        outcome["final_text"],
        dict(
            role=record["role"],
            stage=record["stage"],
            requirements=state["requirements"],
            roots=environment[ROOTS],
            run=run,
            folder=run / record["directory"],
            session_id=unique_session(outcome),
            plan=environment["plan"],
            submission_path=implementation_submission.review_path(run, record["stage"], state),
            plan_reference=state.get("results", {}).get("plan"),
            prior_findings=plan_feedback.pending(run, environment.get("feedback")),
            stage_number=record["number"],
            changed=tool_paths(state["changed_files"], environment[ROOTS]),
            check_config=environment.get("check_config", {}),
            deliver_lines=environment.get("deliver_lines", False),
            rebuilt=record.get("result_rebuild", False),
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


def review_inputs(workflow):
    """Exact reviewable documents of the current plan or implementation revision."""
    state = workflow.state
    run = workflow.run
    stage = workflow.flow["stage"]
    paths = plan_paths(run, stage, state["results"].get("plan"))
    submission = implementation_submission.review_path(run, stage, state)
    if submission:
        paths.append(run / submission)
    return paths
