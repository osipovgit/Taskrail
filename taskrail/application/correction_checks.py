"""Keep local runtime checks selected by every independently reviewed correction."""

from taskrail.application import (
    check_configuration,
    check_specs,
    correction_history,
    planned_checks,
)
from taskrail.core.schema import require


def selected(parent, state, exclude=None):
    """Derive inherited bindings from sealed plans and the original recipe catalog."""
    specs = local(state.get("check_specs", []))
    completed = correction_history.completed(parent, exclude)
    if not completed:
        return specs
    settings = check_configuration.parent_settings(parent, state)
    for run in completed:
        extra = additions(*run, settings, state["requirements"])
        specs = planned_checks.merge(specs, extra)
    return specs


def additions(run, completed, settings, requirements):
    """A correction cannot substitute commands, criteria or bindings from mutable state."""
    frozen = check_configuration.parent_settings(run, completed)
    require(
        check_configuration.fingerprint(settings) == check_configuration.fingerprint(frozen),
        "Correction check catalog changed",
    )
    plan = correction_history.reviewed_plan(run, completed)
    selected = check_specs.from_selections(
        plan.get("check_selections", []), settings.get("check_recipes", {}), requirements
    )
    planned_checks.local_correction(selected, dict(phase="correction"))
    return selected


def local(specs):
    """Integration and corrective writers repeat local checks, retaining remote deferrals."""
    return [spec for spec in specs if spec["phase"] == "check"]
