"""How a stage answers: the plan file for the planner, DONE or BLOCKED for the
implementer, else one JSON object.

Every alternative is the validated contract, printed as compact JSON on one line, so
the request stays small and no line is cut when the model reads it; a schema too long
for one line gets one field per line. SSH and Jenkins requests are listed only when
the executor is installed. The texts live in core/prompt-texts.json.
"""

import json
from types import MappingProxyType

from taskrail.application import executor_contracts, plan_file, progress_file, review_file
from taskrail.core import protected_paths, schema
from taskrail.core.prompt_texts import text

PLANNER = "planner"
IMPLEMENTER = "implementer"
LINE_LIMIT = 1800


FINISHES = MappingProxyType(
    {
        PLANNER: "format.plan_finish",
        IMPLEMENTER: "format.done_finish",
        "plan-reviewer": "format.review_finish",
        "reviewer": "format.review_finish",
    }
)


def finish(stage):
    """The stage's final-result instruction, shared by continuations and corrections."""
    return text(FINISHES.get(stage, "format.json_finish"))


def decisions(stage):
    """The decision rules of a JSON stage: shared rules and the stage's own."""
    return "{} {}".format(text("format.decisions"), text(f"format.decisions.{stage}"))


def continuation(stage, request):
    """Resume the current task with the same output contract as its first turn."""
    resumed = text("format.continuation", stage=stage, request=request, finish=finish(stage))
    return f"\n{resumed}\n"


def correction(stage, error):
    """Correct a rejected result; the continuation that follows restates the format."""
    patch = "" if stage in FINISHES else text("format.patch")
    return "{}\n".format(text("format.correction", error=error, patch=patch))


def section(stage, state, run, config, catalog=None):
    """The response instructions and schemas of a stage."""
    alternatives = executor_contracts.for_stage(stage, run, config, catalog)
    if stage == PLANNER:
        requirements = state.get("requirements", [])
        protected = protected_paths.patterns(config)
        rules = plan_file.instructions(run, config["roots"], requirements, protected)
        routing = text("format.plan_routing")
    elif stage == IMPLEMENTER:
        rules = "\n".join((progress_file.instructions(run), text("format.done")))
        routing = text("format.request_routing")
    else:
        rules = review_file.instructions(run, stage)
        routing = text("format.request_routing")
    return "\n".join([rules, routing, *map(schema_line, alternatives)])


def own_schema(stage, state):
    """The review result contract, for plan review as well."""
    schema.contract_version(state.get("contract_version"))
    return schema.SCHEMAS["decision"]


def schema_line(contract):
    """One compact line, or one field per line when that line would be too long."""
    line = json.dumps(contract, separators=(",", ":"))
    if len(line) < LINE_LIMIT:
        return line
    return json.dumps(contract, indent=1, separators=(",", ":"))
