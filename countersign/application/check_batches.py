"""Execute fixed phase recipes before independent interpretation, without model polling."""

from countersign.application import (
    check_remote,
    check_results,
    check_specs,
    reviewed_plan,
    reviewed_start,
)
from countersign.application.artifacts import new_stage
from countersign.executor import protocol


def run_configured(workflow):
    """Remote phase batches retain source locks, approvals and durable ticket recovery."""
    selected = phase_specs(workflow)
    if not selected:
        return
    workflow.checkpoint()
    active = new_stage(workflow.run, workflow.state, "check", dict(mode="recipe-batch"))
    workflow.open_record(active)
    records = []
    for spec in selected:
        recorded = one(workflow, active[0], spec)
        records.append(recorded)
        if recorded["assessment"]["status"] != "passed":
            break
    workflow.state["checks"] = [summary(record) for record in records]
    workflow.finish_active("CHECK_COMPLETED", workflow.state["checks"])
    if any(record["assessment"]["status"] != "passed" for record in records):
        workflow.state.update(
            status="BLOCKED",
            summary="Configured checks did not pass; inspect their recorded results before continuing",
        )
    else:
        review_completed(workflow, records)


def phase_specs(workflow):
    """Only fixed delivery phases execute remote recipes before independent review."""
    phase = workflow.config.get("phase")
    if phase not in {"validation", "server"}:
        return []
    specs = check_specs.configured(workflow.config, workflow.state["requirements"])
    return [spec for spec in specs if spec["phase"] == phase]


def one(workflow, folder, spec):
    """Reuse a completed check for the same request and source, including known failure."""
    recipe = workflow.config["check_recipes"][spec["recipe_id"]]
    request = protocol.fingerprint(recipe["request"])
    for record in check_results.trusted(workflow.run).values():
        if record["check_id"] == spec["id"] and record["request_sha256"] == request:
            return record
    return check_remote.execute(workflow, folder, spec, recipe)


def summary(record):
    """The model receives bounded facts and a link to immutable check evidence."""
    assessment = record["assessment"]["status"]
    return dict(
        file=record["check_id"],
        check_id=record["check_id"],
        status="PASS" if assessment == "passed" else "FAIL",
        assessment=assessment,
        detail=record["path"],
    )


def review_completed(workflow, records):
    """Fully bound batches need independent interpretation, not another execution plan."""
    expected = {
        entry["id"] for entry in workflow.state["requirements"] if entry["kind"] == "runtime"
    }
    covered = {criterion for record in records for criterion in record["criteria"]}
    if expected and expected <= covered:
        reviewed_start.install(
            workflow,
            reviewed_plan.empty("Review the recorded checks against every criterion"),
            "reviewer",
        )
