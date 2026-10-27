"""The check stage between implementation and independent review."""

from taskrail.application import added_lines, change_limit, transitions, yaml_install
from taskrail.application.artifacts import new_stage
from taskrail.application.builtin_checks import syntax_checks
from taskrail.application.verify_commands import run_commands

CHECKS = "checks"


def run_checks(workflow):
    """Record syntax checks and the added-line scan, then settings commands; route failures to repair."""
    if not change_limit.approved(workflow):
        return
    state = workflow.state
    active = new_stage(workflow.run, state, "check", dict(mode="builtin"))
    workflow.open_record(active)
    checks = collect(workflow, active[0])
    state[CHECKS] = checks
    failed = any(check["status"] == "FAIL" for check in checks)
    workflow.finish_active("CHECK_FAILED" if failed else "CHECK_COMPLETED", checks)
    state["results"][CHECKS] = "{}/result.json".format(active[1]["directory"])
    workflow.guard.verify(
        "Source/Git changed during checks; verification commands must not write inside declared roots"
    )
    transitions.checked(workflow.flow, state, workflow.config["max_repairs"])


def collect(workflow, folder):
    """Commands run only after every changed file passed its syntax and added-line scan."""
    roots = workflow.config["roots"]
    checks = yaml_install.resolve(
        workflow, folder, syntax_checks(roots, workflow.state["changed_files"])
    )
    checks.extend(added_lines.scan(workflow.run, roots, workflow.state["preimages"]))
    if any(check["status"] == "FAIL" for check in checks):
        return checks
    return [*checks, *run_commands(workflow, folder)]
