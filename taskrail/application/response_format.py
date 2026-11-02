"""How a stage answers: the plan file for the planner, DONE or BLOCKED for the
implementer, review.md for reviewers, and executor requests in between.

Git and local requests are shown as one filled-in example each, which weak models
copy more reliably than a schema. SSH and Jenkins requests, listed only when the
executor is installed, keep their validated contract as compact JSON on one line,
because it carries the available targets and jobs; a schema too long for one line gets
one field per line. The texts live in core/prompt-texts.json.
"""

import json
from types import MappingProxyType

from taskrail.application import executor_contracts, plan_file, progress_file, review_file
from taskrail.core import protected_paths
from taskrail.core.prompt_texts import text

PLANNER = "planner"
IMPLEMENTER = "implementer"
LINE_LIMIT = 1800
EXAMPLES = MappingProxyType({"git": "example.git", "local": "example.local"})


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
    return text(FINISHES[stage])


def continuation(stage, request):
    """Resume the current task with the same output contract as its first turn."""
    resumed = text("format.continuation", stage=stage, request=request, finish=finish(stage))
    return f"\n{resumed}\n"


def correction(stage, error):
    """Correct a rejected result; the continuation that follows restates the format."""
    return "{}\n".format(text("format.correction", error=error))


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
    return "\n".join([rules, routing, *request_lines(alternatives)])


def request_lines(alternatives):
    """An example for each Git and local request, then the schema of every other one."""
    examples = [text(EXAMPLES[name]) for name in alternatives if name in EXAMPLES]
    others = (contract for name, contract in alternatives.items() if name not in EXAMPLES)
    return [*examples, *map(schema_line, others)]


def schema_line(contract):
    """One compact line, or one field per line when that line would be too long."""
    line = json.dumps(contract, separators=(",", ":"))
    if len(line) < LINE_LIMIT:
        return line
    return json.dumps(contract, indent=1, separators=(",", ":"))
