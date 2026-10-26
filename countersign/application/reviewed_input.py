"""Freeze authenticated child inputs separately from the verbatim submitted task."""

import json

from countersign.application import child_brief, reviewed_artifacts
from countersign.core import schema, task_spec
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
        context=child_brief.context(parent, step),
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
    heading = child_brief.heading(step)
    return dict(
        title=heading,
        goal=heading,
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


def restore(workflow):
    """Continue the sealed child projection without reopening a mutable parent run."""
    expected = workflow.state.get(SIGNATURE)
    if expected is None:
        schema.require(
            workflow.state.get("phase") != "task",
            "Missing authenticated child input; restart required",
        )
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
