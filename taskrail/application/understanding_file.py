"""A resumable task-understanding draft and its immutable accepted requirements."""

import json
import shutil

from taskrail.application import reviewed_artifacts
from taskrail.core import prompt_texts, schema, task_understanding
from taskrail.core.files import atomic_json

NAME = "understanding.json"
STAGE = task_understanding.STAGE
REQUIREMENTS = "requirements"


def prepare(run):
    """Create the draft once; every retry continues the saved extraction."""
    path = run / NAME
    if not path.exists():
        atomic_json(path, dict(summary="", requirements=[]))
    return path


def instructions(run):
    """The same short file contract is used on first entry and continuation."""
    return prompt_texts.text("understanding.format", path=run / NAME)


def stage_result(context):
    """Resolve exact input references without allowing a source quote to change the task."""
    run = context["run"]
    spec = context["check_config"]["task_spec"]
    payload = json.loads((run / NAME).read_text(), object_pairs_hook=schema.unique_fields)
    verdict = task_understanding.resolve(payload, spec)
    shutil.copyfile(run / NAME, context["folder"] / NAME)
    return dict(verdict, status="UNDERSTOOD")


def install(workflow, verdict):
    """Replace provisional input segmentation once, before any planning or source research."""
    workflow.state[REQUIREMENTS] = verdict[REQUIREMENTS]
    workflow.state["task_spec"][REQUIREMENTS] = verdict[REQUIREMENTS]
    workflow.config["task_spec"][REQUIREMENTS] = verdict[REQUIREMENTS]


def restore(workflow):
    """Continue with the accepted identities, never re-segment the original task."""
    reference = workflow.state["results"].get(STAGE)
    if reference is None:
        return
    verdict = reviewed_artifacts.document(workflow.run, reference)
    schema.require(
        verdict[REQUIREMENTS] == workflow.state[REQUIREMENTS], "Accepted task requirements changed"
    )
    install(workflow, verdict)
