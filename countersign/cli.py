"""One task file is the normal entry point."""

import argparse
import functools
import sys
from pathlib import Path

from countersign import cli_service

ERROR_PREFIX = "Error: "
SETTINGS_OPTION = "--settings"
COMMAND_ARGUMENT = "command"
SUCCESS = frozenset(("READY_FOR_REVIEW", "NO_CHANGES_REQUIRED", "TASKS_READY"))
FAILED = 2
INTERRUPTED = 130
FAILURES = (ValueError, OSError, KeyError)


def main():
    """Dispatch a subcommand; a task file alone runs the task."""
    argv = sys.argv[1:] or ["serve"]
    commands = dict(
        web=cli_service.serve_command,
        serve=cli_service.serve_command,
        status=cli_service.status_command,
        resume=resume_command,
        check=cli_service.check_command,
        init=cli_service.init_command,
        analytics=cli_service.analytics_command,
    )
    return commands.get(argv[0], run_command)(argv)


def run_command(argv):
    """Launch a fresh workflow on the original roots."""
    if argv[0] == "run":
        argv = argv[1:]
    args = run_arguments(argv)
    options = dict(debug=args.debug, run_dir=args.run_dir, plan_response=args.plan_response)
    return guarded(functools.partial(run_task, args.task, args.settings, **options))


def run_arguments(argv):
    """Arguments of a fresh run."""
    parser = argparse.ArgumentParser(
        description="Run a task on original projects: plan, implement, check, review. Controlled Git access; no full copies or automatic rollback."
    )
    parser.add_argument(
        "task", help="Task Markdown file; countersign-task header declares project roots"
    )
    parser.add_argument(
        SETTINGS_OPTION,
        help="Settings JSON; defaults to $COUNTERSIGN_SETTINGS, then the installed settings",
    )
    parser.add_argument("--run-dir", help="New log directory outside projects (normally automatic)")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--plan-response",
        help="Use a saved response as an untrusted draft for fresh planning and review",
    )
    return parser.parse_args(argv)


def resume_command(argv):
    """Continue through the same guarded execution path as the UI."""
    parser = argparse.ArgumentParser(
        description="Continue an interrupted run after source integrity checks"
    )
    parser.add_argument(COMMAND_ARGUMENT)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(SETTINGS_OPTION)
    parser.add_argument(
        "--extend-budget",
        action="store_true",
        help="Grant two more launches and one attempt timeout to the stopped stage; keep consumed usage",
    )
    parser.add_argument(
        "--note",
        help="Note for the agents, e.g. that a missing tool is now installed; the task still applies",
    )
    args = parser.parse_args(argv)
    resume = "extend" if args.extend_budget else True
    options = dict(run_dir=args.run_dir, resume=resume, note=args.note)
    task = args.run_dir / "00-input/task.md"
    return guarded(functools.partial(run_task, task, args.settings, **options))


def run_task(task, settings, **options):
    """Exit code 0 only for a reviewed result."""
    from countersign.application.live import execute_task

    status = execute_task(task, settings, **options)[1]
    return 0 if status in SUCCESS else FAILED


def guarded(action):
    """Report expected failures without a traceback."""
    try:
        return action()
    except KeyboardInterrupt:
        return INTERRUPTED
    except FAILURES as error:
        sys.stderr.write(f"{ERROR_PREFIX}{error}\n")
        return FAILED


if __name__ == "__main__":
    sys.exit(main())
