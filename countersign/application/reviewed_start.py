"""Start reviewed atomic children and integration review from server-owned contracts."""

from countersign.application import (
    check_configuration,
    planned_checks,
    reviewed_artifacts,
    reviewed_input,
    reviewed_plan,
    reviewed_sources,
    task_scope,
)
from countersign.application.changes import capture_preimages
from countersign.application.plan_validation import canonical_plan
from countersign.core import schema, task_lineage
from countersign.core.files import atomic_json

PLAN = "plan"
REQUIREMENTS = "requirements"
REFERENCE = "00-input/reviewed-plan.json"


def begin(workflow):
    """Legacy child runs still plan; authenticated contracts skip redundant model planning."""
    phase = workflow.config.get("phase")
    if phase == "integration":
        stage = "check" if workflow.config.get("check_specs") else "reviewer"
        install(
            workflow,
            reviewed_plan.empty("Review the combined result against every criterion"),
            stage,
        )
    elif phase == "task" and workflow.config.get("assigned_contract"):
        child(workflow)


def child(workflow):
    """Recheck authority, dependency results, roots and source freshness under the run lock."""
    assignment = workflow.config["assigned_contract"]
    parent = reviewed_artifacts.parent(workflow.run.parent, assignment["parent_run"])
    if parent is None:
        return
    by_id = {step["id"]: step for step in parent[PLAN]["steps"]}
    schema.require(assignment["task_id"] in by_id, "Unknown reviewed child task")
    step = by_id[assignment["task_id"]]
    reviewed_sources.verify(parent, step["id"], workflow)
    verify_requirements(parent, step, workflow)
    check_configuration.adopt(workflow, parent["run"], parent["state"])
    reviewed_input.capture(workflow, parent, step)
    plan = reviewed_plan.single(step, workflow.state[REQUIREMENTS])
    plan = canonical_plan(plan, workflow.config["roots"])
    task_scope.check(plan, workflow.config)
    planned_checks.install(
        workflow, planned_checks.inherit(parent["state"], workflow.state[REQUIREMENTS])
    )
    install(workflow, plan, "implementer")


def verify_requirements(parent, step, workflow):
    """A task header cannot replace the criteria or goal of a reviewed parent task."""
    expected = task_lineage.for_step(parent["state"][REQUIREMENTS], step)
    schema.require(
        expected == workflow.state[REQUIREMENTS],
        "Child criteria changed; parent replanning required",
    )
    fields = workflow.config["task_spec"]["fields"]
    fields = {field["name"]: field["text"] for field in fields}
    goal = "; ".join(step["done_when"]) or step["action"]
    schema.require(fields.get("goal") == goal, "Child goal changed; parent replanning required")


def install(workflow, plan, stage):
    """Materialize the contract and capture original bytes before the first child writer."""
    atomic_json(workflow.run / REFERENCE, plan)
    workflow.state["results"][PLAN] = REFERENCE
    workflow.state["contract_start"] = dict(stage=stage, origin="reviewed-contract")
    workflow.flow.update(plan=plan, allowed=plan["proposed_change_files"], stage=stage)
    if stage == "implementer":
        capture_preimages(
            workflow.run,
            workflow.config["roots"],
            workflow.flow["allowed"],
            workflow.state["preimages"],
        )
