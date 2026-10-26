"""Chronological run artifacts; one authoritative result per stage."""

from datetime import datetime, timezone
from types import MappingProxyType

from taskrail.application.stage_console import announce
from taskrail.core.files import atomic_json
from taskrail.core.paths import tool_paths

PHASES = MappingProxyType(
    {
        "planner": "plan",
        "plan-reviewer": "plan-review",
        "implementer": "implement",
        "reviewer": "review",
        "check": "check",
    }
)
TOKEN_FIELDS = ("input", "output", "reasoning", "cache_read", "cache_write", "total")
DIAGNOSTICS = (
    "elapsed_seconds",
    "exit_code",
    "tokens",
    "errors",
    "tool_errors",
    "contract_error",
    "warnings",
)
STATUS = "status"
MODEL = "model"
NO_DETAILS = MappingProxyType({})


def save_run(run, state):
    """Write the run index with call, time and token totals."""
    attempts = state["attempts"]
    elapsed = sum(attempt.get("elapsed_seconds", 0) for attempt in attempts)
    state["metrics"] = dict(
        calls=len(attempts), elapsed_seconds=round(elapsed, 3), tokens=token_totals(attempts)
    )
    atomic_json(run / "run.json", state)


def token_totals(attempts):
    """Reported token usage summed over attempts."""
    totals = dict.fromkeys(TOKEN_FIELDS, 0)
    for attempt in attempts:
        usage = attempt.get("tokens", {})
        for field in TOKEN_FIELDS:
            totals[field] += usage.get(field, 0)
    return totals


def new_stage(run, state, stage, attempt=NO_DETAILS):
    """Open the next numbered stage folder; attempt may name role, mode and model."""
    number = len(state["stages"]) + 1
    folder = "-".join((format(number, "02d"), PHASES[stage]))
    run.joinpath(folder).mkdir()
    record = stage_record(number, folder, stage, attempt, state["results"])
    state["stages"].append(record)
    state["stage"] = stage
    atomic_json(run / folder / "stage.json", record)
    save_run(run, state)
    return run / folder, record


def stage_record(number, folder, stage, attempt, inputs):
    """The stage record with its inputs: the task, earlier results and the role."""
    role = attempt.get("role")
    record = dict(number=number, directory=folder, stage=stage, role=role)
    record["mode"] = attempt.get("mode", MODEL)
    record.update(status="RUNNING", started_at=now())
    if attempt.get(MODEL):
        record[MODEL] = attempt[MODEL]
    record["inputs"] = dict(task="00-input/task.md", **inputs)
    if role:
        record["inputs"]["role"] = f"00-input/agents/{role}.md"
    return record


def finish_stage(run, state, active, outcome):
    """Close a stage; outcome holds status and optionally result and diagnostics."""
    path, record = active
    record.update(status=outcome[STATUS], finished_at=now())
    diagnostics = outcome.get("diagnostics") or {}
    record.update({key: diagnostics[key] for key in DIAGNOSTICS if key in diagnostics})
    verdict = tool_paths(outcome.get("result"), state.get("roots", {}))
    announce(record, verdict)
    if verdict is not None:
        atomic_json(path / "result.json", verdict)
    files = [entry.name for entry in path.iterdir() if entry.is_file()]
    record["files"] = sorted(files)
    atomic_json(path / "stage.json", record)
    save_run(run, state)


def now():
    """UTC timestamp of stage records."""
    return datetime.now(timezone.utc).isoformat()
