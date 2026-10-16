"""Chronological run artifacts; one authoritative result per stage."""

from datetime import datetime, timezone

from countersign.core.files import atomic_json
from countersign.core.paths import tool_paths
from countersign.observability.progress import clock

PHASES = {
    "planner": "plan",
    "plan-reviewer": "plan-review",
    "implementer": "implement",
    "reviewer": "review",
    "check": "check",
}


def save_run(run, state):
    state["metrics"] = {
        "calls": len(state["attempts"]),
        "elapsed_seconds": round(
            sum(attempt.get("elapsed_seconds", 0) for attempt in state["attempts"]), 3
        ),
        "tokens": {
            key: sum(attempt.get("tokens", {}).get(key, 0) for attempt in state["attempts"])
            for key in ("input", "output", "reasoning", "cache_read", "cache_write", "total")
        },
    }
    atomic_json(run / "run.json", state)


def new_stage(run, state, stage, role=None, mode="model", model=None):
    number = len(state["stages"]) + 1
    folder = "%02d-%s" % (number, PHASES[stage])
    path = run / folder
    path.mkdir()
    record = dict(
        number=number,
        directory=folder,
        stage=stage,
        role=role,
        mode=mode,
        status="RUNNING",
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    if model:
        record["model"] = model
    record["inputs"] = dict(task="00-input/task.md", **state["results"])
    if role:
        record["inputs"]["role"] = f"00-input/agents/{role}.md"
    state["stages"].append(record)
    state["stage"] = stage
    atomic_json(path / "stage.json", record)
    save_run(run, state)
    return path, record


def finish_stage(run, state, path, record, status, result=None, diagnostics=None):
    record["status"] = status
    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    if diagnostics:
        record.update(
            {
                key: diagnostics[key]
                for key in (
                    "elapsed_seconds",
                    "exit_code",
                    "tokens",
                    "errors",
                    "tool_errors",
                    "contract_error",
                    "warnings",
                )
                if key in diagnostics
            }
        )
    result = tool_paths(result, state.get("roots", {}))
    for warning in record.get("warnings", []):
        print(
            "  Warning: "
            + warning.get(
                "resolution",
                "Invalid offset recovered by a later full read of "
                + str(warning.get("input", {}).get("filePath", "")),
            ),
            flush=True,
        )
    if isinstance(result, dict) and "status" in result:
        record["verdict"] = result["status"]
        record["summary"] = result.get("summary", "")
        print(
            "  [%s] Result [%s]: %s" % (clock(), record["directory"], result["status"]), flush=True
        )
        if record["summary"]:
            print("  %s" % record["summary"].replace("\n", "\n  "), flush=True)
        for finding in result.get("findings", []):
            print(
                "  Finding: {criterion} — {evidence}".format(
                    criterion=finding.get("criterion", ""),
                    evidence=finding.get("evidence", ""),
                ),
                flush=True,
            )
        for text in result.get("blocking_gaps", []) + result.get("unverified", []):
            print(f"  Not verified: {text}", flush=True)
    if isinstance(result, list):
        for check in result:
            print("  Check: {file} — {status}: {detail}".format(**check), flush=True)
    if result is not None:
        atomic_json(path / "result.json", result)
    record["files"] = sorted(artifact.name for artifact in path.iterdir() if artifact.is_file())
    atomic_json(path / "stage.json", record)
    save_run(run, state)
