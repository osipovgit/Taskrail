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
JSON_FINISH = "Return the complete final stage result as one JSON object, with no prose or fences."
PLAN_FINISH = (
    "Update the plan.md file named in your request only if its content needs correction. "
    "Missing observed evidence needs a direct read of the cited source range, not a cosmetic "
    "plan edit or unrelated citations. Then end with DONE. Do not return a JSON stage result."
)
DECISIONS = (
    "\nAuthor semantic decisions only using schema_version=2. Cover every assigned requirement "
    "once; use its short R<n> label or stable ID. Evidence references are absolute path:from-to "
    "or a delivered source handle such as S1:10-12. New source reads use absolute paths. "
    "A handle proves only the listed lines and becomes stale when the file changes. "
    "Provide reason for contradicted, gap, not_evaluated or deferred outcomes; routine "
    "satisfied/planned outcomes need no explanation. Findings name observed evidence and "
    "the concrete defect. Implementers use unresolved outcomes, not findings. "
    "The server derives status, changed files, completed steps and deferred check text; "
    "do not repeat them. missing_inputs names required unavailable input. "
    "Plan review may mark runtime work planned only when an approved step owns the criterion "
    "and a selected or configured local recipe checks it. Remote runtime checks remain deferred; "
    "final runtime satisfaction requires a matching current CheckResult.\n"
)
CORRECTION = (
    "For an addressed correction to your rejected V2 draft, you may instead return "
    '{"schema_version":2,"corrections":[{"path":"/outcomes/0/result","value":"satisfied"}]}. '
    "Only semantic decision fields may change; the complete merged draft is validated again. "
    "Use an existing array index or replace a whole array. Do not resend unaffected decisions. "
)


def finish(stage):
    """The stage's final-result instruction, shared by continuations and corrections."""
    return PLAN_FINISH if stage == PLANNER else JSON_FINISH


def continuation(stage, request):
    """Resume the current task with the same output contract as its first turn."""
    return (
        f"\nContinue the SAME task using existing context. Do not restart research. "
        f"You are the {stage} stage; your instructions are in {request}. "
        "Planner and reviewer stages never change project files. "
        "For another executor operation return one advertised request object as your entire "
        f"message. Otherwise {finish(stage)}\n"
    )


def correction(stage, error):
    """Correct a rejected result without changing the stage's representation."""
    addressed = "" if stage == PLANNER else CORRECTION
    return (
        f"Your final result was rejected, so the stage did not finish: {error}\n"
        "Fix exactly this in the same session. Re-read cited lines if needed and keep "
        f"the rest of the result. {addressed}{finish(stage)}\n"
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
        text = DECISIONS + ROUTING
    return "{0}{1}\n".format(text, "\n".join(map(schema_line, alternatives)))


def own_schema(stage, state):
    """The stage result contract; plan review uses the reviewer's."""
    schema.contract_version(state.get("contract_version"))
    return schema.SCHEMAS["decision"]


def schema_line(contract):
    """One compact line, or one field per line when that line would be too long."""
    line = json.dumps(contract, separators=(",", ":"))
    if len(line) < LINE_LIMIT:
        return line
    return json.dumps(contract, indent=1, separators=(",", ":"))
