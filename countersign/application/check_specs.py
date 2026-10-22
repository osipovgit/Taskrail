"""Checks reference server recipes and assigned criteria, never inferred shell text."""

from countersign.application.check_recipes import parse_catalog as parse_catalog
from countersign.core.schema import require
from countersign.executor import protocol

RECIPE = "recipe_id"
CRITERIA = "criteria"
PHASE = "phase"
FIELDS = frozenset(("id", RECIPE, CRITERIA, PHASE, "parameters"))
IDENTIFIER = "id"
SELECTION_FIELDS = frozenset((RECIPE, CRITERIA))
IDENTITY_LENGTH = 16


def parse_specs(specs, catalog):
    """Reject ambiguous or unavailable recipes while preserving check order."""
    require(isinstance(specs, list), "check_specs must be a list")
    parsed = [parse_spec(spec, catalog) for spec in specs]
    names = [spec[IDENTIFIER] for spec in parsed]
    require(len(names) == len(set(names)), "Duplicate check ID")
    return parsed


def parse_spec(spec, catalog):
    """A closed reference to one exact server-owned recipe."""
    require(isinstance(spec, dict) and set(spec) == FIELDS, "Invalid CheckSpec fields")
    protocol.label(spec[IDENTIFIER])
    require(spec[RECIPE] in catalog, "Unknown check recipe")
    recipe = catalog[spec[RECIPE]]
    require(spec[PHASE] == recipe[PHASE], "Check phase differs from server recipe")
    criteria = spec[CRITERIA]
    require(isinstance(criteria, list) and bool(criteria), "Check needs criterion IDs")
    valid = all(isinstance(name, str) and name for name in criteria)
    require(valid, "Invalid check criteria")
    require(len(criteria) == len(set(criteria)), "Duplicate check criterion")
    arguments = spec["parameters"]
    require(
        isinstance(arguments, dict) and not arguments, "Exact recipes reject parameter overrides"
    )
    return dict(spec)


def validate_specs(specs, catalog, requirements):
    """Every criterion belongs to this frozen task and is explicitly runtime verification."""
    parsed = parse_specs(specs, catalog)
    runtime = {entry[IDENTIFIER] for entry in requirements if entry["kind"] == "runtime"}
    for spec in parsed:
        require(set(spec[CRITERIA]) <= runtime, "Check references unknown runtime criteria")
    return parsed


def configured(config, requirements):
    """Resolve configured checks once the task's stable requirement IDs are known."""
    return validate_specs(
        config.get("check_specs", []), config.get("check_recipes", {}), requirements
    )


def from_selections(selections, catalog, requirements):
    """A planner selects recipe and criteria; the server owns IDs and execution phase."""
    require(isinstance(selections, list), "Check selections must be a list")
    specs = [selected_spec(selection, catalog) for selection in selections]
    return validate_specs(specs, catalog, requirements)


def selected_spec(selection, catalog):
    """No model-provided argv, phase, timeout or adapter crosses this boundary."""
    require(
        isinstance(selection, dict) and set(selection) == SELECTION_FIELDS,
        "Invalid check selection",
    )
    recipe = selection[RECIPE]
    require(recipe in catalog, "Unknown check recipe")
    signature = protocol.fingerprint(selection)[:IDENTITY_LENGTH]
    return dict(
        id=f"check-{signature}",
        recipe_id=recipe,
        criteria=selection[CRITERIA],
        phase=catalog[recipe][PHASE],
        parameters={},
    )
