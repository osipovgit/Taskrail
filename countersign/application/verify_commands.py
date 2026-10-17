"""Run verification commands from server settings in the check stage.

They run without a shell, as the service user, with a filtered environment, and
must not change files inside declared roots.
"""

import shlex

from countersign.interactions import local

TAIL_CHARACTERS = 2000
REASON = "Verification command from server settings"
LOG_NAME = "verify-{0:02d}.log"
CWD = "cwd"
ARGV = "argv"
FAIL = "FAIL"


def run_commands(workflow, folder):
    """Run the commands whose cwd is a declared root of this run, in settings order."""
    locations = command_roots(workflow.config)
    selected = [
        dict(entry, cwd=locations[entry[CWD]])
        for entry in workflow.config["verify_commands"]
        if entry[CWD] in locations
    ]
    return [
        run_command(workflow, folder / LOG_NAME.format(number), command)
        for number, command in enumerate(selected, 1)
    ]


def command_roots(config):
    """Configured cwd -> effective root; an isolated run uses the source root's worktree."""
    roots = [str(root) for root in config["roots"].values()]
    locations = dict(zip(roots, roots))
    for entry in config["worktrees"].values():
        locations[entry["source"]] = entry["worktree"]
    return locations


def run_command(workflow, log, command):
    """Return a check record; the output is kept in the check stage folder."""
    payload = dict(cwd=command[CWD], argv=command[ARGV], reason=REASON)
    timeout = command["timeout_seconds"]
    try:
        outcome = local.execute(
            payload, dict(timeout=timeout, roots=workflow.config["roots"], run=workflow.run)
        )
    except (ValueError, OSError) as error:
        return check_record(command, FAIL, str(error))
    log.write_text("{stdout}\n--- stderr ---\n{stderr}".format(**outcome), encoding="utf-8")
    detail = "exit {0}; log {1}".format(outcome["exit_code"], log.name)
    if outcome["exit_code"] == 0:
        return check_record(command, "PASS", detail)
    return check_record(command, FAIL, failure_detail(detail, outcome))


def check_record(command, status, detail):
    """Check records share the shape of built-in syntax checks."""
    command_line = shlex.join(command[ARGV])
    return dict(file=command_line, cwd=command[CWD], status=status, detail=detail)


def failure_detail(detail, outcome):
    """Repair feedback ends with the output tail, where test runners report failures."""
    combined = "{stdout}{stderr}".format(**outcome)
    return "{0}; output tail:\n{1}".format(detail, combined[-TAIL_CHARACTERS:])
