"""Mandatory task gates select exact local recipes without inventing runtime criteria."""

from taskrail.core.schema import require
from taskrail.executor import protocol

KEY = "required_local_checks"
RECIPE = "recipe_id"
IDENTITY_LENGTH = 16


def names(plan):
    """Keep each selected recipe once in reviewed task order."""
    selected = []
    for step in (plan or {}).get("steps", []):
        selected.extend(step.get("required_checks", []))
    require(all(isinstance(name, str) for name in selected), "Required checks need recipe IDs")
    return list(dict.fromkeys(selected))


def validate(selected, catalog):
    """Only local catalog recipes can become mandatory implementation checks."""
    require(isinstance(selected, list), "Required checks must be a list of recipe IDs")
    for name in selected:
        require(isinstance(name, str) and name in catalog, "Unknown required check recipe")
        recipe = catalog[name]
        require(
            recipe["phase"] == "check" and recipe["kind"] == "local",
            "Required checks must select local check recipes",
        )


def install(workflow, plan):
    """Persist the reviewed gates for this run and later combined integration."""
    selected = names(plan)
    if workflow.config.get("phase") == "correction":
        inherited = workflow.config.get(KEY, [])
        selected = list(dict.fromkeys(inherited + selected))
    validate(selected, workflow.config.get("check_recipes", {}))
    workflow.config[KEY] = selected
    workflow.state[KEY] = selected


def selected(config):
    """Gates have recorded results but do not claim an unassigned criterion is satisfied."""
    names = config.get(KEY, [])
    catalog = config.get("check_recipes", {})
    validate(names, catalog)
    return [entry(name, catalog[name]) for name in names]


def entry(name, recipe):
    """A stable gate identity survives restart and includes its recipe in public results."""
    identity = protocol.fingerprint(dict(recipe_id=name))[:IDENTITY_LENGTH]
    spec = dict(id=f"step-{identity}", recipe_id=name, criteria=[])
    return dict(spec=spec, recipe=recipe, required=True)
