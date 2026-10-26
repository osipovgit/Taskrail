"""How a stage answers: the plan file for the planner, else one JSON object.

Every alternative is the validated contract, printed as compact JSON on one line, so
the request stays small and no line is cut when the model reads it; a schema too long
for one line gets one field per line. SSH and Jenkins requests are listed only when
the executor is installed. The texts live in core/prompt-texts.json.
"""

import json
from pathlib import Path

from taskrail.application import executor_contracts, plan_file
from taskrail.core import protected_paths, schema
from taskrail.core.prompt_texts import text
from taskrail.executor import protocol

PLANNER = "planner"
IMPLEMENTER = "implementer"
LINE_LIMIT = 1800


def finish(stage):
    """The stage's final-result instruction, shared by continuations and corrections."""
    return text("format.plan_finish" if stage == PLANNER else "format.json_finish")


def decisions(stage):
    """The decision rules of a JSON stage: shared rules and the stage's own."""
    return "{} {}".format(text("format.decisions"), text(f"format.decisions.{stage}"))


def continuation(stage, request):
    """Resume the current task with the same output contract as its first turn."""
    resumed = text("format.continuation", stage=stage, request=request, finish=finish(stage))
    return f"\n{resumed}\n"


def correction(stage, error):
    """Correct a rejected result; the continuation that follows restates the format."""
    patch = "" if stage == PLANNER else text("format.patch")
    return "{}\n".format(text("format.correction", error=error, patch=patch))


def section(stage, state, run, config):
    """The response instructions and schemas of a stage."""
    alternatives = [executor_contracts.git_schema(), executor_contracts.local_schema()]
    if Path(protocol.SOCKET).exists():
        alternatives.extend([executor_contracts.ssh_schema(), executor_contracts.jenkins_schema()])
    if stage == PLANNER:
        requirements = state.get("requirements", [])
        protected = protected_paths.patterns(config)
        rules = plan_file.instructions(run, config["roots"], requirements, protected)
        routing = text("format.plan_routing")
    else:
        alternatives.insert(0, own_schema(stage, state))
        rules = decisions(stage)
        routing = text("format.routing")
    return "\n".join([rules, routing, *map(schema_line, alternatives)])


def own_schema(stage, state):
    """The stage result contract; plan review uses the reviewer's."""
    schema.contract_version(state.get("contract_version"))
    name = "implementer-decision" if stage == IMPLEMENTER else "decision"
    return schema.SCHEMAS[name]


def schema_line(contract):
    """One compact line, or one field per line when that line would be too long."""
    line = json.dumps(contract, separators=(",", ":"))
    if len(line) < LINE_LIMIT:
        return line
    return json.dumps(contract, indent=1, separators=(",", ":"))
