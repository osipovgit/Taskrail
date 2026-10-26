"""Validate recovery inputs and preserve observations without replaying a writer."""

from countersign.application import budget_extensions, evidence, instruction_sources
from countersign.application.artifacts import finish_stage


def verify_preimages(run, state, before):
    """A preimage must still be the byte version recorded at the start or inherited."""
    for name, reference in state["preimages"].items():
        if reference:
            source_bytes = (run / reference).read_bytes()
            expected = recorded_digest(name, state, before)
            if instruction_sources.fingerprint(source_bytes) != expected:
                raise ValueError("Saved preimage changed; cannot continue safely")


def recorded_digest(name, state, before):
    """An inherited preimage's digest, or the file's digest when the run started."""
    inherited = state.get("inherited_preimages", {}).get(name)
    signature = before.get(name) or ""
    return inherited or signature.rsplit(":", 1)[-1]


def observations(run, state, stage, roots):
    """Restore source reads from the latest matching read-only attempt."""
    if stage == "implementer":
        return None
    for record in reversed(state["stages"]):
        events = run / record["directory"] / "events.jsonl"
        if record.get("stage") == stage and events.is_file():
            return evidence.refresh(run, events, roots.values())
    return None


def interrupt_open_records(run, state):
    """Finish abandoned records while keeping their raw events and diagnostics."""
    for record in state["stages"]:
        if record["status"] == "RUNNING":
            errors = ["Previous process stopped before finishing this stage."]
            outcome = dict(status="INTERRUPTED", diagnostics={"errors": errors})
            finish_stage(run, state, (run / record["directory"], record), outcome)


def extend_budget(run, stage, config):
    """Grant only after checkpoint integrity validation under the execution lock."""
    budget_extensions.grant(run, stage, config)
