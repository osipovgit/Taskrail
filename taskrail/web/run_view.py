"""The dashboard view of one run: index, stages, artifacts and allowed actions."""

import re
from pathlib import Path

from taskrail.core.paths import tool_paths
from taskrail.observability.progress import clock
from taskrail.web import delivery_state, history, lifecycle, run_errors, run_family, split_approvals
from taskrail.web.run_activity import activity
from taskrail.web.run_files import contained, optional_json, stage_telemetry, text_tail
from taskrail.web.run_messages import public_messages
from taskrail.web.run_sources import (
    find_submission,
    launch_record,
    run_state,
    valid_record,
)

RUN_ID = re.compile(r"[A-Za-z0-9_.-]+")
CONSOLE_LIMIT = 30000
ROOTS = "roots"
STARTED = "started_at"


def run_view(base, name):
    """Everything the dashboard shows for one run; paths are shown as tool paths."""
    if not RUN_ID.fullmatch(name) or name in {".", ".."}:
        raise ValueError("Invalid run ID")
    run = contained(base, name)
    try:
        return readable_view(base, name, run)
    except run_errors.ERRORS as error:
        if not run.is_dir() or run.is_symlink():
            raise
        return run_errors.view(run, error)


def readable_view(base, name, run):
    """Build the normal view only when its persisted authority can be read."""
    submission = find_submission(Path(base), name)
    launch = launch_record(submission)
    state = run_state(run, launch)
    stages = stage_views(run, state)
    return dict(
        id=name,
        launch=launch,
        parent=parent_view(run, submission),
        **index_view(state, stages),
        **context_view(run, submission, state),
    )


def parent_view(run, submission):
    """The split or delivery a task or phase run belongs to, shown in that parent's card."""
    folder = run if run.joinpath(history.TASK_FILE).is_file() else submission
    if not run_family.shown_inside(run.parent, folder):
        return None
    run_name, slot = run_family.parent_link(folder)
    return dict(run=run_name, slot=slot)


def stage_views(run, state):
    """Views of the well-formed stage records."""
    roots = state.get(ROOTS, {})
    records = [record for record in state.get("stages", []) if valid_record(record)]
    return [stage_view(run, record, roots) for record in records]


def stage_view(run, record, roots):
    """A stage record with its result, chat messages, activity and telemetry."""
    directory = record["directory"]
    stage = dict(record)
    stage["result"] = tool_paths(optional_json(run, f"{directory}/result.json"), roots)
    stage["summary"] = tool_paths(stage.get("summary", ""), roots)
    messages = public_messages(contained(run, f"{directory}/events.jsonl"))
    stage["messages"] = tool_paths(messages, roots)
    stage["activity"] = optional_json(run, f"{directory}/activity.json")
    telemetry = dict(stage_telemetry(run, directory))
    telemetry["timeline"] = tool_paths(telemetry["timeline"], roots)
    stage["telemetry"] = telemetry
    return stage


def index_view(state, stages):
    """Status, timing, requirements and changes from the run index."""
    roots = state.get(ROOTS, {})
    first_stage = next((stage.get(STARTED) for stage in stages), None)
    return dict(
        phase=state.get("phase"),
        started_at=state.get(STARTED) or first_stage,
        finished_at=state.get("finished_at"),
        server_time=clock(),
        monitoring=state.get("monitoring", {}),
        execution_jobs=state.get("execution_jobs", []),
        requirements=state.get("requirements", []),
        status=state.get("status"),
        summary=tool_paths(state.get("summary", ""), roots),
        roots=roots,
        changed_files=tool_paths(state.get("changed_files", []), roots),
        unverified=state.get("unverified", []),
        outside_changes=state.get("outside_changes"),
        review_limits=state.get("review_limits", []),
        metrics=state.get("metrics", {}),
        stages=stages,
    )


def context_view(run, submission, state):
    """Conversation, draft, actions and text artifacts of the run and its launcher."""
    started = run.joinpath(history.TASK_FILE).is_file()
    task = contained(run, history.TASK_FILE) if started else contained(submission, "task.md")
    return dict(
        conversation=history.previous_messages(run) if started else [],
        draft=history.task_draft(run) if run.joinpath("run.json").exists() else None,
        actions=lifecycle.actions(run, state, activity(run)),
        auto_approve=split_approvals.shown(run, state),
        delivery=delivery_state.view(run, state),
        pending_approval=lifecycle.pending_approval(run),
        task=text_tail(task),
        console=text_tail(contained(submission, "console.log"), CONSOLE_LIMIT),
        report=text_tail(contained(run, "report.md")),
        diff=text_tail(contained(run, "changes.diff")),
        design=text_tail(contained(run, "design.md")),
    )
