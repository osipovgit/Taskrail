"""Record sandbox fallback and missing verification tools before expensive model work."""

from taskrail.application import check_runner, check_selection, check_stage
from taskrail.core.files import atomic_json
from taskrail.infrastructure import sandbox
from taskrail.interactions import approval_policy, local, local_request
from taskrail.observability.progress import say

KEY = "local_preflight"


def prepare(workflow):
    """Resolve required tools without executing commands or granting host approval."""
    tools = [availability(workflow, check) for check in required(workflow)]
    allowed = approval_policy.active(workflow.run, workflow.state)
    explanation = sandbox.health(allowed)[1]
    report = dict(sandbox=sandbox.mode(), explanation=explanation, tools=tools)
    if workflow.state.get(KEY) != report:
        say(report["explanation"])
    workflow.state[KEY] = report
    atomic_json(workflow.run / "local-preflight.json", report)
    missing = [entry["program"] for entry in tools if entry["executable"] is None]
    if missing:
        raise ValueError(
            "Required local tools are unavailable: {}. Install them on the orchestrator host "
            "or correct the selected check, then continue; no command was executed.".format(
                ", ".join(sorted(set(missing)))
            )
        )


def required(workflow):
    """Remote delivery phases and research without bound checks need no local tools."""
    if workflow.config.get("phase") in {"validation", "server"}:
        return []
    return check_selection.applicable(workflow) if check_stage.required(workflow) else []


def availability(workflow, check):
    """Validate cwd and command policy now, but leave exact action approval to execution."""
    request = check_runner.request_for(check)
    argv = local_request.checked_request(request, workflow.config["roots"])
    program = None
    if not local_request.missing_executable(argv):
        program = local.validate(request, workflow.config["roots"])[0]
    identifier = check["spec"]["id"]
    return dict(check_id=identifier, program=argv[0], executable=program)
