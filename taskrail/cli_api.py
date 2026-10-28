"""Automation commands: submit tasks, answer approvals and control runs without the UI.

They use the same launcher, validation and run store as the browser, print one JSON
object and return at once; the task runs in a detached worker. A chat bot or script
on the server can therefore start a task, answer the agents' questions and follow a
run. Automatic steps of a split (the next task, integration review, Jenkins
validation) still need the managed service, as in the browser.
"""

import argparse
import json
import sys
from pathlib import Path

from taskrail import cli_requests, cli_runs

ERROR_PREFIX = "Error: "
FAILURES = (ValueError, OSError, KeyError)


def submit_command(argv):
    """Start a task in a detached worker; prints {"id", "status"}."""
    args = submit_parser().parse_args(argv[1:])
    return answered(lambda: cli_runs.launcher(args).submit(cli_requests.task_payload(args)))


def decide_command(argv):
    """Answer the approval a run waits for: allow, deny or an alternative."""
    parser = parser_for("decide", decide_command.__doc__)
    parser.add_argument("run")
    parser.add_argument("decision", choices=("allow", "deny", "alternative"))
    parser.add_argument("--text", default="", help="The alternative, or a note for a denial")
    parser.add_argument("--allow-all", action="store_true", help="Allow all further actions")
    args = parser.parse_args(argv[1:])
    return answered(lambda: cli_runs.decide(args))


def action_command(argv):
    """Run a lifecycle action: stop, resume, resume_budget, confirm, epic_next and others."""
    parser = parser_for("action", action_command.__doc__)
    parser.add_argument("run")
    parser.add_argument("action")
    parser.add_argument("--note", help="A note for the agents when continuing")
    parser.add_argument("--task", help="The task of a split that the action names")
    args = parser.parse_args(argv[1:])
    return answered(lambda: cli_runs.launcher(args).action(cli_runs.action_payload(args)))


def status_command(argv):
    """The status of a run, the approval it waits for and its delivery step, as JSON."""
    parser = parser_for("status", status_command.__doc__)
    parser.add_argument("run")
    args = parser.parse_args(argv[1:])
    return answered(lambda: cli_runs.status(args))


def submit_parser():
    """Options of a new task, a follow-up or a restart."""
    parser = parser_for("submit", submit_command.__doc__)
    parser.add_argument("--json", dest="payload", help="Task fields as JSON: a file or -")
    parser.add_argument("--root", action="append", default=[], help="ALIAS=PATH, repeatable")
    for field in (*cli_requests.FIELDS, "verification"):
        option = "--{}".format(field.replace("_", "-"))
        parser.add_argument(option, help="Text, or @FILE to read it from a file")
    parser.add_argument("--mode", choices=tuple(cli_requests.MODES), default="develop")
    parser.add_argument("--allow-all", action="store_true", help="Allow all actions of the run")
    parser.add_argument(
        "--in-place", action="store_true", help="Edit the roots instead of new Git worktrees"
    )
    parser.add_argument("--followup", metavar="RUN", help="Continue the conversation of RUN")
    parser.add_argument("--restart", metavar="RUN", help="Start RUN again from scratch")
    return parser


def parser_for(name, description):
    """A subcommand parser with the shared settings and run store options."""
    parser = argparse.ArgumentParser(prog=f"taskrail {name}", description=description)
    parser.add_argument("--settings")
    parser.add_argument("--runs-dir", type=Path)
    return parser


def answered(action):
    """Print the result as JSON; expected failures become an error line and exit code 2."""
    try:
        outcome = action()
    except FAILURES as error:
        sys.stderr.write(f"{ERROR_PREFIX}{error}\n")
        return 2
    text = json.dumps(outcome, ensure_ascii=False, indent=2)
    sys.stdout.write(f"{text}\n")
    return 0
