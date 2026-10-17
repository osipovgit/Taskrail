"""Prepare model attempts without mixing contracts, budgets and workflow transitions."""

import hashlib
import sys

from countersign.application import budgets
from countersign.application.artifacts import save_run
from countersign.core.files import atomic_json
from countersign.infrastructure.artifact_access import manifest
from countersign.observability.progress import clock

STAGE = "stage"


def prepare(run, record, config, state):
    """Reserve durable resources and disclose the effective instruction source."""
    limits = {
        "timeout": config["timeout"],
        "seconds": config["stage_seconds"],
        "attempts": config["stage_attempts"],
    }
    allowance = budgets.reserve(run, record, limits)
    role = record["role"]
    role_directory = state["agent_source_directory"]
    record.update(
        budget=allowance,
        contract_version=state["contract_version"],
        agent_source=f"{role_directory}/{role}.md",
        contract_sha256=hashlib.sha256((run / "00-input/contract.json").read_bytes()).hexdigest(),
        agent_sha256=state["agent_sources"][role],
    )
    return record


def save_request(folder, record, request, state):
    """Store exactly what is sent to the model with its reproducible fingerprint."""
    (folder / "tool-result.md").touch(exist_ok=True)
    if record["mode"] != "format-repair":
        access = folder / "access.json"
        atomic_json(
            access,
            manifest(folder.parent, folder, state["roots"], record.get("writable_files", [])),
        )
        request = request.replace(
            "# Orchestrator instructions\n",
            f"# Orchestrator instructions\nRead access manifest: {access}. Use only listed run artifacts.\n",
            1,
        )
    request = with_allowance(request, record["budget"])
    (folder / "request.md").write_text(request, encoding="utf-8")
    record["instruction_modules"] = (
        [] if record["mode"] == "format-repair" else state.get("instruction_modules", [])
    )
    record["instruction_sha256"] = hashlib.sha256(request.encode()).hexdigest()
    atomic_json(folder / "stage.json", record)
    save_run(folder.parent, state)


def failure_status(error):
    """Keep budget exhaustion distinguishable from an integrity/configuration stop."""
    return "STAGE_BUDGET_EXCEEDED" if isinstance(error, budgets.BudgetExceeded) else "BLOCKED"


def record_outcome(run, state, record, outcome):
    """Settle durable consumption and index the process outcome before validation."""
    budgets.settle(run, record["directory"], outcome)
    status = "AGENT_COMPLETED" if outcome["status"] == "OK" else outcome["status"]
    elapsed = outcome["elapsed_seconds"]
    record.update(elapsed_seconds=elapsed, tokens=outcome.get("tokens", {}))
    sys.stdout.write(f"  [{clock()}] {status} {elapsed:.1f}s\n")
    sys.stdout.flush()
    attempt = outcome.copy()
    attempt.pop("final_text", None)
    path = str(run / record["directory"])
    attempt.update(stage=record[STAGE], path=path)
    state["attempts"].append(attempt)
    return attempt


def with_allowance(request, budget):
    """Add runtime allowance after the task without editing verbatim user input."""
    head, marker, tail = request.rpartition("# Orchestrator instructions\n")
    if not marker:
        return request
    return f"{head}{marker}Effective observed allowance: {budget}\n{tail}"
