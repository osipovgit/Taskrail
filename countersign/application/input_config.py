"""Canonical task input and server-owned verification recipes."""

from countersign.application import check_parents, check_specs
from countersign.core import task_spec

PHASE = "phase"


def input_configuration(text, meta, options, checks_override=None):
    """Resolve typed inputs and server-owned recipe identities before launch."""
    spec = task_spec.resolve(text, meta)
    if meta.get(PHASE) == "task" and not meta.get("assigned_contract"):
        raise ValueError("A task of a split needs an authenticated parent contract")
    recipes = (
        check_specs.parse_catalog(options)
        if checks_override is None
        else checks_override.get("check_recipes", {})
    )
    return dict(
        task_spec=spec,
        assigned_contract=meta.get("assigned_contract"),
        check_parent=check_parents.reference(meta),
        check_recipes=recipes,
        check_specs=check_specs.parse_specs(meta.get("check_specs", []), recipes),
    )
