"""Prepare model attempts without mixing contracts, budgets and workflow transitions."""

import hashlib
import sys

from taskrail.application import source_packet
from taskrail.application.artifacts import save_run
from taskrail.core import prompt_texts, protected_paths
from taskrail.core.files import atomic_json
from taskrail.infrastructure.artifact_access import manifest
from taskrail.observability.progress import clock

STAGE = "stage"


def prepare(run, record, config, state):
    """Reserve durable resources and disclose the effective instruction source."""
    role = record["role"]
    role_directory = state["agent_source_directory"]
    record.update(
        timeout_seconds=config["timeout"],
        contract_version=1,
        agent_source=f"{role_directory}/{role}.md",
        contract_sha256=hashlib.sha256((run / "00-input/contract.json").read_bytes()).hexdigest(),
        agent_sha256=state["agent_sources"][role],
    )
    return record


def remaining(workflow, stage):
    """Automatic retries and repairs share a steering deadline; Continue starts fresh."""
    spent = workflow.runtime.setdefault("stage_elapsed", {})
    return max(0, workflow.config["timeout"] - spent.get(stage, 0))


def save_request(folder, record, request, workflow):
    """Store exactly what is sent to the model with its reproducible fingerprint."""
    state = workflow.state
    access = folder / "access.json"
    rights = (state["roots"], record.get("writable_files", []))
    protected = protected_paths.patterns(workflow.config)
    atomic_json(access, manifest(folder.parent, folder, *rights, protected))
    request = request.replace(
        "# Orchestrator instructions\n",
        "# Orchestrator instructions\n{}\n".format(
            prompt_texts.text("request.manifest", path=access)
        ),
        1,
    )
    (folder / "request.md").write_text(request, encoding="utf-8")
    source_packet.queue_delivery(folder.parent, folder, record[STAGE], request)
    record["instruction_modules"] = state.get("instruction_modules", [])
    record["instruction_sha256"] = hashlib.sha256(request.encode()).hexdigest()
    atomic_json(folder / "stage.json", record)
    save_run(folder.parent, state)


def record_outcome(run, state, record, outcome):
    """Settle durable consumption and index the process outcome before validation."""
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
