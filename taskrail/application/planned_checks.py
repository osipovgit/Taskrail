"""Bind reviewed recipe selections to runtime criteria without model-authored commands."""

from taskrail.application import check_specs, check_stage, local_preflight, step_checks
from taskrail.core import prompt_texts
from taskrail.core.schema import require

SPECS = "check_specs"
RECIPES = "check_recipes"
CRITERIA = "criteria"
IDENTIFIER = "id"


def validate(plan, config):
    """Unknown recipes and criterion bindings are format errors before plan review."""
    selections = plan.get("check_selections", [])
    step_checks.validate(step_checks.names(plan), config.get(RECIPES, {}))
    if selections:
        selected = check_specs.from_selections(
            selections, config.get(RECIPES, {}), config["task_spec"]["requirements"]
        )
        local_correction(selected, config)


def activate(workflow):
    """Only a reviewed plan may extend the checks selected in the original task."""
    plan = workflow.flow["plan"]
    if workflow.state.get("plan_review", {}).get("status") != "APPROVE":
        return
    chosen = check_specs.from_selections(
        plan.get("check_selections", []),
        workflow.config.get(RECIPES, {}),
        workflow.state["requirements"],
    )
    local_correction(chosen, workflow.config)
    install(workflow, chosen)
    step_checks.install(workflow, plan)
    local_preflight.prepare(workflow)
    check_stage.schedule(workflow)


def local_correction(selected, config):
    """The bounded corrective workflow cannot change remote delivery bindings."""
    if config.get("phase") == "correction":
        require(
            all(spec["phase"] == "check" for spec in selected),
            prompt_texts.text("correction.local_checks"),
        )


def install(workflow, chosen):
    """Keep existing stable check IDs and reject collisions rather than replacing them."""
    merged = merge(workflow.config.get(SPECS, []), chosen)
    workflow.config[SPECS] = merged
    workflow.state[SPECS] = merged


def merge(existing, chosen):
    """One recipe/criterion binding runs once, even when explicitly selected twice."""
    indexed = {spec[IDENTIFIER]: spec for spec in existing}
    bindings = {binding(spec) for spec in existing}
    for spec in chosen:
        require(indexed.get(spec[IDENTIFIER], spec) == spec, "Conflicting reviewed check ID")
        if binding(spec) not in bindings:
            indexed[spec[IDENTIFIER]] = spec
            bindings.add(binding(spec))
    return list(indexed.values())


def binding(spec):
    """Criterion order is presentation, not a reason to repeat the same exact recipe."""
    return spec["recipe_id"], tuple(sorted(spec[CRITERIA]))


def inherit(parent, requirements):
    """An atomic child receives only local checks bound to its inherited runtime IDs."""
    identities = {
        entry.get("parent_id", entry[IDENTIFIER]): entry[IDENTIFIER]
        for entry in requirements
        if entry["kind"] == "runtime"
    }
    chosen = []
    for spec in parent.get(SPECS, []):
        criteria = [identities[name] for name in spec[CRITERIA] if name in identities]
        if spec["phase"] == "check" and criteria:
            chosen.append(dict(spec, criteria=criteria))
    return chosen
