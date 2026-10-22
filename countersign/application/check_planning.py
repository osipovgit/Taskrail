"""Planning capabilities for runtime checks, distinct from executed acceptance evidence."""

from countersign.application import check_specs
from countersign.core.coverage import PLANNING


def criteria(payload, context):
    """Only an owned local recipe may be planned before its check is executed."""
    stage = context["stage"]
    if stage not in PLANNING:
        return set()
    plan = payload if stage == "planner" else context.get("plan") or {}
    owned = {name for step in plan.get("steps", []) for name in step["criteria"]}
    outcomes = plan.get("coverage", [])
    planned = {entry["id"] for entry in outcomes if entry["outcome"] == "planned"}
    return owned & planned & local_criteria(plan, context)


def local_criteria(plan, context):
    """Validate catalog bindings before trusting a model's selected recipe IDs."""
    config = context.get("check_config", {})
    specs = check_specs.configured(config, context["requirements"])
    specs.extend(
        check_specs.from_selections(
            plan.get("check_selections", []),
            config.get("check_recipes", {}),
            context["requirements"],
        )
    )
    return {name for spec in specs if spec["phase"] == "check" for name in spec["criteria"]}
