"""Return a concrete interpretation defect to the task-understanding stage."""

import json
import re

from taskrail.application import plan_feedback, repair_feedback
from taskrail.core import json_response, reply_frame, schema, task_understanding
from taskrail.core.files import digest

STATUS = "REINTERPRET_TASK"
STAGES = frozenset(("planner", "plan-reviewer"))


def requested(response, context):
    """A quoted input defect is a stage handoff, never an executor operation."""
    if STATUS not in response or reply_frame.submitted(response):
        return None
    body = json_response.body(response)
    if not body.startswith("{"):
        return None
    try:
        payload = json.loads(body, object_pairs_hook=schema.unique_fields)
    except (ValueError, RecursionError) as error:
        if re.search(rf'"status"\s*:\s*"{STATUS}"', response):
            raise ValueError("Expected one complete interpretation correction object") from error
        return None
    if payload.get("status") != STATUS:
        return None
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
    sources = json.dumps(verdict["sources"], sort_keys=True)
    feedback = dict(
        summary=verdict["summary"], findings=[], blocking_gaps=[verdict["summary"], sources]
    )
    prior = plan_feedback.packet(flow.get("feedback"))
    if prior:
        feedback["previous_feedback"] = prior
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
