"""Freeze authenticated child inputs separately from the verbatim submitted task."""

import json

from countersign.application import reviewed_artifacts
from countersign.core import schema, task_graph, task_spec
from countersign.core.files import atomic_json, digest

REFERENCE = "00-input/reviewed-task-spec.json"
SIGNATURE = "reviewed_input_sha256"
REQUIREMENTS = "requirements"
SPEC = "task_spec"
CANONICAL = "reviewed_input"


def capture(workflow, parent, step):
    """No supplied display field can add instructions to an already approved child."""
    entries = workflow.state[REQUIREMENTS]
    spec = task_spec.from_fields(fields(step, entries))
    spec.update(
        requirements=entries,
        assigned_requirements=entries,
        context=context(parent, step),
        task_sha256=digest(workflow.config["task_text"].encode()),
    )
    atomic_json(workflow.run / REFERENCE, spec)
    workflow.state[SIGNATURE] = digest(reviewed_artifacts.read(workflow.run, REFERENCE))
    workflow.config[SPEC] = spec
    workflow.config[CANONICAL] = True
    workflow.state[SPEC] = spec


def fields(step, requirements):
    """Only the reviewed action, exact owned obligations and global constraints remain."""
    global_constraints = [entry for entry in requirements if global_constraint(entry)]
    criteria = [
        criterion(entry)
        for entry in requirements
        if entry["kind"] == "task" and not global_constraint(entry)
    ]
    return dict(
        title="{id}: {action}".format(**step),
        goal=step["action"],
        criteria="\n\n".join(criteria),
        entry_points="\n".join(step["files"]),
        constraints="\n\n".join(entry["text"] for entry in global_constraints),
    )


def global_constraint(entry):
    """Global scope comes from the authenticated parent's original field boundary."""
    return entry.get("source", {}).get("field") == "constraints"


def criterion(entry):
    """A narrowed assignment keeps its complete original text and explicit scope."""
    text = entry["text"]
    scope = entry.get("scope")
    return f"{text}\nOnly this assigned part: {scope}" if scope else text


def context(parent, step):
    """Use the authenticated contract, not a user-supplied sibling summary, for dispatch."""
    dependencies = task_graph.ancestors(parent["plan"]["steps"], step["id"])
    contract = dict(current_task=step, completed_prerequisites=sorted(dependencies))
    return "Reviewed atomic task; earlier dependencies are verified complete.\n{0}".format(
        json.dumps(contract)
    )


def restore(workflow):
    """Continue the sealed child projection without reopening a mutable parent run."""
    expected = workflow.state.get(SIGNATURE)
    if expected is None:
        origin = workflow.state.get("contract_start", {}).get("origin")
        required = workflow.state.get("phase") == "task" and origin == "reviewed-contract"
        schema.require(not required, "Missing authenticated child input; restart required")
        return
    encoded = reviewed_artifacts.read(workflow.run, REFERENCE)
    schema.require(
        digest(encoded) == expected, "Reviewed child input changed; continuation refused"
    )
    spec = json.loads(encoded)
    validate(spec, workflow)
    workflow.config[SPEC] = spec
    workflow.config[CANONICAL] = True
    workflow.state[SPEC] = spec


def validate(spec, workflow):
    """The persisted projection retains its schema, exact obligations and original task."""
    metadata = {key: spec[key] for key in task_spec.SPEC_KEYS if key in spec}
    task_spec.checked(metadata)
    schema.require(
        spec[REQUIREMENTS] == workflow.state[REQUIREMENTS], "Reviewed child requirements changed"
    )
    schema.require(
        spec["task_sha256"] == digest(workflow.config["task_text"].encode()),
        "Reviewed child original task changed",
    )
