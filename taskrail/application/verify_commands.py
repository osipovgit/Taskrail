"""Run verification commands from server settings in the check stage.

They run without a shell, as the service user, with a filtered environment, and
must not change files inside declared roots.
"""

import shlex

from taskrail.application import check_outcomes, check_runner, check_selection
from taskrail.core import prompt_texts

TAIL_CHARACTERS = 2000
STATUS = "status"
LOG_NAME = "verify-{0:02d}.log"
CWD = "cwd"
ARGV = "argv"
RECIPE = "recipe"


def run_commands(workflow, folder, *, prerequisite_failed=False):
    """Run the commands whose cwd is a declared root of this run, in settings order."""
    selected = check_selection.applicable(workflow.config, workflow.state["requirements"])
    if prerequisite_failed:
        return [not_started(check) for check in selected]
    return [
        run_command(workflow, folder / LOG_NAME.format(number), chosen)
        for number, chosen in enumerate(selected, 1)
    ]


def not_started(check):
    """Keep scheduled commands visible when an earlier prerequisite failed."""
    row = check_record(
        check[RECIPE]["request"], "NOT_STARTED", prompt_texts.text("checks.prerequisite")
    )
    return dict(row, check_id=check["spec"]["id"], started=False)


def run_command(workflow, log, check):
    """Return a check record; the output is kept in the check stage folder."""
    command = check[RECIPE]["request"]
    try:
        outcome, recorded = check_runner.execute(workflow, log.parent, check)
    except (ValueError, OSError) as error:
        return dict(
            check_record(command, "UNVERIFIED", str(error)),
            check_id=check["spec"]["id"],
            execution_status="UNCONFIRMED",
            assessment="unknown",
        )
    return outcome_record(command, outcome, recorded, log)


def outcome_record(command, outcome, recorded, log):
    """Readable command logs accompany the canonical immutable check evidence."""
    output = {name: outcome.get(name, "") for name in ("stdout", "stderr")}
    log.write_text("{stdout}\n--- stderr ---\n{stderr}".format(**output), encoding="utf-8")
    assessment = recorded["assessment"]
    status = check_outcomes.STATUS_BY_ASSESSMENT[assessment[STATUS]]
    detail = outcome_detail(outcome, recorded)
    if status != "PASS" and any(output.values()):
        detail = failure_detail(detail, output)
    return dict(
        check_record(command, status, detail),
        execution_status=outcome[STATUS],
        assessment=assessment[STATUS],
        started=check_outcomes.observed_start(outcome),
        check_id=recorded["check_id"],
        result_id=recorded["id"],
    )


def outcome_detail(outcome, recorded):
    """Preserve the process outcome, operator alternative and adapter diagnosis."""
    facts = [outcome[STATUS]]
    if outcome.get("exit_code") is not None:
        facts.append("exit {}".format(outcome["exit_code"]))
    reasons = (
        outcome.get("reason"),
        outcome.get("decision", {}).get("alternative"),
        recorded["assessment"].get("detail"),
    )
    facts.extend(filter(None, reasons))
    facts.append("evidence {}".format(recorded["path"]))
    return "; ".join(facts)


def check_record(command, status, detail):
    """Check records share the shape of built-in syntax checks."""
    command_line = shlex.join(command[ARGV])
    return dict(file=command_line, cwd=command[CWD], status=status, detail=detail)


def failure_detail(detail, outcome):
    """Repair feedback ends with the output tail, where test runners report failures."""
    combined = "{stdout}{stderr}".format(**outcome)
    tail = combined[-TAIL_CHARACTERS:]
    return f"{detail}; output tail:\n{tail}"
