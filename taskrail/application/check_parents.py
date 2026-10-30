"""Authenticate delivery check lineage before adopting a parent's frozen recipes."""

import json

from taskrail.application import (
    check_configuration,
    check_stage,
    delivery_confirmation,
    execution_context,
    integration_changes,
    reviewed_artifacts,
    run_state,
    step_checks,
)
from taskrail.application.correction_checks import selected as corrective_specs
from taskrail.application.correction_history import required as corrective_gates
from taskrail.core import delivery_record
from taskrail.core.files import digest
from taskrail.core.schema import require

PARENT = "check_parent"
INTEGRATION = "integration"
PHASES = frozenset((INTEGRATION, "validation", "server", "correction"))
LOCAL_PHASES = frozenset((INTEGRATION, "correction"))
FINISHED = frozenset(("READY_FOR_REVIEW", "NO_CHANGES_REQUIRED", "TASKS_READY"))
REQUIREMENTS = "requirements"
SPECS = "check_specs"
PHASE = "phase"
SEAL = "check_parent_sha256"


def reference(meta):
    """A claimed parent is syntax only; its durable child link is checked under the lock."""
    name = meta.get(PARENT)
    if name is not None:
        require(meta.get(PHASE) in PHASES, "Check parent requires a delivery check phase")
        require(
            isinstance(name, str) and bool(delivery_record.RUN_NAME.fullmatch(name)),
            "Invalid check parent run",
        )
    return name


def adopt(workflow, resume=False):
    """Only the phase actually linked by a completed parent inherits its recipes."""
    name = reference(workflow.config)
    if name is None:
        if workflow.config.get(PHASE) == INTEGRATION and check_stage.required(workflow):
            workflow.flow["stage"] = "check"
        return
    if workflow.config[PHASE] == "server":
        require(
            delivery_record.server_checks_confirmed(workflow.run, name),
            "Server checks require personal confirmation",
        )
        delivery_confirmation.verify(workflow.run.parent / name)
    if resume and restored(workflow):
        return
    parent = reviewed_artifacts.run_path(workflow.run.parent, name)
    state = reviewed_artifacts.document(parent, "run.json")
    verify(workflow, parent, state)
    execution_context.adopt(workflow, parent, state)
    check_configuration.adopt(workflow, parent, state)
    if workflow.config[PHASE] in LOCAL_PHASES:
        selected = state.get(step_checks.KEY, [])
        selected = corrective_gates(parent, selected, workflow.config, workflow.run.name)
        workflow.config[step_checks.KEY] = selected
        workflow.state[step_checks.KEY] = selected
    workflow.state[SEAL] = receipt(workflow)
    if workflow.config[PHASE] == INTEGRATION:
        integration_changes.capture(workflow, parent)
        if check_stage.required(workflow):
            workflow.flow["stage"] = "check"


def restored(workflow):
    """Continue an authenticated phase from its own unchanged adoption record."""
    expected = workflow.state.get(SEAL)
    if expected is None:
        return False
    require(expected == receipt(workflow), "Inherited check phase inputs changed")
    check_configuration.frozen(workflow.run, workflow.state)
    return True


def receipt(workflow):
    """Bind inherited configuration to the exact phase, roots and criterion assignments."""
    payload = dict(
        parent=workflow.config[PARENT],
        phase=workflow.config[PHASE],
        settings=check_configuration.fingerprint(workflow.config),
        roots=run_state.stored_roots(workflow.config["roots"]),
        requirements=workflow.state[REQUIREMENTS],
        specs=workflow.config.get(SPECS, []),
        required_checks=workflow.config.get(step_checks.KEY, []),
    )
    return digest(json.dumps(payload, sort_keys=True).encode())


def verify(workflow, parent, state):
    """Metadata alone cannot choose another run's commands or acceptance criteria."""
    phase = workflow.config[PHASE]
    require(state["status"] in FINISHED, "Check parent is not complete")
    require(
        state["roots"] == run_state.stored_roots(workflow.config["roots"]),
        "Check parent roots differ",
    )
    phases = delivery_record.read(parent).get("phases", {})
    require(phases.get(phase) == workflow.run.name, "Check parent does not link this phase")
    selected = selected_specs(state, phase)
    if phase in LOCAL_PHASES:
        selected = corrective_specs(parent, state, workflow.run.name)
    require(workflow.config.get(SPECS, []) == selected, "Parent check bindings changed")
    verify_requirements(workflow, state, selected)


def selected_specs(state, phase):
    """Integration repeats local checks; delivery runs only its declared remote phase."""
    selected = "check" if phase in LOCAL_PHASES else phase
    return [spec for spec in state.get(SPECS, []) if spec[PHASE] == selected]


def verify_requirements(workflow, state, specs):
    """Every inherited check retains the original runtime obligation, including its text."""
    original = {entry["id"]: entry for entry in state[REQUIREMENTS]}
    current = {entry["id"]: entry for entry in workflow.state[REQUIREMENTS]}
    criteria = {criterion for spec in specs for criterion in spec["criteria"]}
    if workflow.config[PHASE] in LOCAL_PHASES:
        criteria = set(original)
    if workflow.config[PHASE] == "correction":
        require(current == original, "Parent check requirements changed")
    require(criteria <= original.keys(), "Unknown parent check requirement")
    require(
        all(current.get(name) == original[name] for name in criteria),
        "Parent check requirements changed",
    )
