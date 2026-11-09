"""Return a concrete interpretation defect to the task-understanding stage."""

import json

from taskrail.application import repair_feedback
from taskrail.core import json_response, schema, task_understanding
from taskrail.core.files import digest

STATUS = "REINTERPRET_TASK"
STAGES = frozenset(("planner", "plan-reviewer"))


def requested(response, context):
    """A quoted input defect is a stage handoff, never an executor operation."""
    if STATUS not in response:
        return None
    payload = json_response.extract(response, schema.unique_fields)
    schema.validate(payload, schema.SCHEMAS["input-revision"])
    schema.require(context["stage"] in STAGES, "Only planning stages can request reinterpretation")
    schema.require(bool(payload["sources"]), "An interpretation correction needs original quotes")
    fields = context["check_config"]["task_spec"]["fields"]
    fields = {field["name"]: field["text"] for field in fields}
    references = []
    for source in payload["sources"]:
        references.append(task_understanding.reference(source, fields))
    return dict(payload, source_spans=references)


def route(flow, state, verdict, version):
    """Retry while the full understanding or the set of reported defects makes progress."""
    summary = verdict["summary"]
    sources = json.dumps(verdict["sources"], sort_keys=True)
    feedback = dict(summary=summary, findings=[], blocking_gaps=[summary, sources])
    feedback["input_correction"] = verdict
    version = json.dumps([version, state["requirements"]], sort_keys=True)
    version = digest(version.encode())
    repair_feedback.route(flow, state, task_understanding.STAGE, feedback, version)
    if state["status"] != "RUNNING":
        return
    flow["plan"] = None
    for key in ("plan", "plan-review"):
        state["results"].pop(key, None)
    state.pop("reviewed_plan_sha256", None)
    state.pop("plan_review", None)
