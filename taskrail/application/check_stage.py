"""The check stage between implementation and independent review."""

from taskrail.application import (
    added_lines,
    check_outcomes,
    check_selection,
    transitions,
    yaml_install,
)
from taskrail.application.artifacts import new_stage
from taskrail.application.builtin_checks import syntax_checks
from taskrail.application.verify_commands import run_commands

CHECKS = "checks"
STATUS = "status"


def schedule(workflow):
    """An approved no-change plan must still execute its applicable local verification."""
    terminal = workflow.state[STATUS] in {"NO_CHANGES_REQUIRED", "READY_FOR_REVIEW"}
    if terminal and not workflow.flow["allowed"] and required(workflow):
        workflow.state[STATUS] = "RUNNING"
        workflow.flow["stage"] = "check"


def required(workflow):
    """Engineering results keep their gates; research executes explicitly bound checks."""
    checks = check_selection.applicable(workflow.config, workflow.state["requirements"])
    engineering = not workflow.config.get("read_only")
    integration = workflow.config.get("phase") == "integration"
    bound = any(check["spec"]["criteria"] for check in checks)
    return bool(checks) and (engineering or integration or bound)


def run_checks(workflow):
    """Record syntax checks and the added-line scan, then settings commands; route failures to repair."""
    state = workflow.state
    active = new_stage(workflow.run, state, "check", dict(mode="builtin"))
    workflow.open_record(active)
    checks, summary = collect(workflow, active[0])
    active[1]["summary"] = summary
    state[CHECKS] = checks
    failed = any(map(check_outcomes.blocks, checks))
    workflow.finish_active("CHECK_FAILED" if failed else "CHECK_COMPLETED", checks)
    state["results"][CHECKS] = "{}/result.json".format(active[1]["directory"])
    workflow.guard.verify(
        "Source/Git changed during checks; verification commands must not write inside declared roots"
    )
    transitions.checked(workflow.flow, state, workflow.work_version())


def collect(workflow, folder):
    """Commands run only after every changed file passed its syntax and added-line scan."""
    roots = workflow.config["roots"]
    syntax = yaml_install.resolve(
        workflow, folder, syntax_checks(roots, workflow.state["changed_files"])
    )
    findings = added_lines.scan(workflow.run, roots, workflow.state["preimages"])
    prerequisites = [*syntax, *findings]
    commands = run_commands(
        workflow, folder, prerequisite_failed=any(map(check_outcomes.blocks, prerequisites))
    )
    return [*prerequisites, *commands], check_outcomes.summary(syntax, commands)
