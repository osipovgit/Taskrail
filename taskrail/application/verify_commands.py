"""Run verification commands from server settings in the check stage.

They run without a shell, as the service user, with a filtered environment, and
must not change files inside declared roots.
"""

import shlex

from taskrail.application import check_runner, check_selection

TAIL_CHARACTERS = 2000
REASON = "Verification command from server settings"
LOG_NAME = "verify-{0:02d}.log"
CWD = "cwd"
ARGV = "argv"
FAIL = "FAIL"
RECIPE = "recipe"


def run_commands(workflow, folder):
    """Run the commands whose cwd is a declared root of this run, in settings order."""
    locations = command_roots(workflow.config)
    selected = check_selection.mapped_checks(check_runner.selected(workflow), locations)
    return [
        run_command(workflow, folder / LOG_NAME.format(number), chosen)
        for number, chosen in enumerate(selected, 1)
    ]


def command_roots(config):
    """Configured cwd -> effective root; an isolated run uses the source root's worktree."""
    roots = [str(root) for root in config["roots"].values()]
    locations = {root: root for root in roots}
    for entry in config["worktrees"].values():
        locations[entry["source"]] = entry["worktree"]
    return locations


def run_command(workflow, log, check):
    """Return a check record; the output is kept in the check stage folder."""
    command = check[RECIPE]["request"]
    try:
        outcome, recorded = check_runner.execute(workflow, log.parent, check)
    except (ValueError, OSError) as error:
        return check_record(command, FAIL, str(error))
    return outcome_record(command, outcome, recorded, log)


def outcome_record(command, outcome, recorded, log):
    """Readable legacy logs accompany the canonical immutable check evidence."""
    output = {name: outcome.get(name, "") for name in ("stdout", "stderr")}
    log.write_text("{stdout}\n--- stderr ---\n{stderr}".format(**output), encoding="utf-8")
    detail = "exit {}; evidence {}".format(outcome.get("exit_code", "unknown"), recorded["path"])
    status = "PASS" if recorded["assessment"]["status"] == "passed" else FAIL
    if status == FAIL:
        detail = failure_detail(detail, output)
    return dict(
        check_record(command, status, detail),
        check_id=recorded["check_id"],
        result_id=recorded["id"],
    )


def check_record(command, status, detail):
    """Check records share the shape of built-in syntax checks."""
    command_line = shlex.join(command[ARGV])
    return dict(file=command_line, cwd=command[CWD], status=status, detail=detail)


def failure_detail(detail, outcome):
    """Repair feedback ends with the output tail, where test runners report failures."""
    combined = "{stdout}{stderr}".format(**outcome)
    tail = combined[-TAIL_CHARACTERS:]
    return f"{detail}; output tail:\n{tail}"
