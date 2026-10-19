"""The check stage between implementation and independent review."""

from countersign.application import transitions
from countersign.application.artifacts import new_stage
from countersign.application.builtin_checks import syntax_checks
from countersign.application.verify_commands import run_commands

CHECKS = "checks"


def run_checks(workflow):
    """Record syntax checks, then settings commands, and route failures to repair."""
    state = workflow.state
    active = new_stage(workflow.run, state, "check", dict(mode="builtin"))
    workflow.open_record(active)
    checks = collect(workflow, active[0])
    state[CHECKS] = checks
    failed = any(check["status"] == "FAIL" for check in checks)
    workflow.finish_active("CHECK_FAILED" if failed else "CHECK_COMPLETED", checks)
    state["results"][CHECKS] = "{0}/result.json".format(active[1]["directory"])
    workflow.guard.verify(
        "Source/Git changed during checks; verification commands must not write inside declared roots"
    )
    transitions.checked(workflow.flow, state, workflow.config["max_repairs"])


def collect(workflow, folder):
    """Commands run only after every changed file passed its syntax check."""
    checks = syntax_checks(workflow.config["roots"], workflow.state["changed_files"])
    if any(check["status"] == "FAIL" for check in checks):
        return checks
    return [*checks, *run_commands(workflow, folder)]
