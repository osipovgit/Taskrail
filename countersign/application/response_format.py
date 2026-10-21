"""How a stage answers: the plan file for the planner, else one JSON object.

Every alternative is the validated contract, printed as compact JSON on one line, so
the request stays small and no line is cut when the model reads it; a schema too long
for one line gets one field per line. SSH and Jenkins requests are listed only when
the executor is installed.
"""

import json
from pathlib import Path

from countersign.application import executor_contracts, plan_file
from countersign.core import schema
from countersign.executor import protocol

PLANNER = "planner"
LINE_LIMIT = 1800
ROUTING = (
    "\nRESPONSE ROUTING: return exactly one JSON object, no prose or fences. For an executor "
    "operation use the advertised GIT_REQUEST, LOCAL_REQUEST, ACTION_REQUEST or JENKINS_REQUEST "
    "object INSTEAD of the stage-result schema and end your turn. Otherwise use the stage-result "
    "alternative, the first schema below. ACTION_REQUEST and JENKINS_REQUEST are only available "
    "when advertised. An intermediate request is not a tool call and not a final task verdict.\n"
    "Response schemas, one alternative per line:\n"
)
PLAN_ROUTING = (
    "\nRESPONSE ROUTING: the plan file is your result; end with DONE. For an executor "
    "operation return one advertised request object as your entire final message and end your "
    "turn; it is not a tool call. Request schemas, one per line:\n"
)


def section(stage, state, run, roots):
    """The response instructions and schemas of a stage."""
    alternatives = [executor_contracts.git_schema(), executor_contracts.local_schema()]
    if Path(protocol.SOCKET).exists():
        alternatives.extend([executor_contracts.ssh_schema(), executor_contracts.jenkins_schema()])
    if stage == PLANNER:
        text = plan_file.instructions(run, roots, state.get("requirements", [])) + PLAN_ROUTING
    else:
        alternatives.insert(0, own_schema(stage, state))
        text = ROUTING
    return "{0}{1}\n".format(text, "\n".join(map(schema_line, alternatives)))


def own_schema(stage, state):
    """The stage result contract; plan review uses the reviewer's."""
    schema.contract_version(state.get("contract_version"))
    return schema.SCHEMAS["reviewer" if stage == "plan-reviewer" else stage]


def schema_line(contract):
    """One compact line, or one field per line when that line would be too long."""
    line = json.dumps(contract, separators=(",", ":"))
    if len(line) < LINE_LIMIT:
        return line
    return json.dumps(contract, indent=1, separators=(",", ":"))
