"""One task file is the normal entry point."""

import argparse
import json
import sys
from pathlib import Path

ERROR_PREFIX = "Error: "
SETTINGS_OPTION = "--settings"
COMMAND_ARGUMENT = "command"


def main():
    argv = sys.argv[1:] or ["serve"]
    commands = dict(
        web=serve_command,
        serve=serve_command,
        status=status_command,
        resume=resume_command,
        check=check_command,
        init=init_command,
    )
    return commands.get(argv[0], run_command)(argv)


def check_command(argv):
    """Verify settings, the opencode CLI, permission enforcement and run storage."""
    parser = argparse.ArgumentParser(description=check_command.__doc__)
    parser.add_argument(COMMAND_ARGUMENT)
    parser.add_argument(SETTINGS_OPTION)
    from countersign.onboarding import check

    failures = 0
    for passed, message in check(parser.parse_args(argv).settings):
        failures += not passed
        sys.stdout.write("{0} {1}\n".format("OK  " if passed else "FAIL", message))
    return 1 if failures else 0


def init_command(argv):
    """Create ~/.config/countersign/settings.json; prompts on a terminal for missing values."""
    parser = argparse.ArgumentParser(description=init_command.__doc__)
    parser.add_argument(COMMAND_ARGUMENT)
    parser.add_argument("--opencode", help="opencode command, default: opencode on PATH")
    parser.add_argument("--model", action="append", default=[], help="ROLE=provider/model")
    parser.add_argument("--format-repair-tools", choices=("none", "read"))
    parser.add_argument("--force", action="store_true", help="Replace existing settings")
    args = parser.parse_args(argv)
    from countersign.onboarding import init

    try:
        target = init(args.opencode, args.model, args.format_repair_tools, force=args.force)
    except (OSError, ValueError) as error:
        sys.stderr.write(f"{ERROR_PREFIX}{error}\n")
        return 2
    sys.stdout.write(f"Wrote {target}. Run: countersign check\n")
    return 0


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
    args = parser.parse_args(argv)
    from countersign.application.live import execute_task

    try:
        _, status = execute_task(
            args.run_dir / "00-input/task.md",
            args.settings,
            run_dir=args.run_dir,
            resume="extend" if args.extend_budget else True,
        )
        return 0 if status in ("READY_FOR_REVIEW", "NO_CHANGES_REQUIRED") else 2
    except (ValueError, OSError, KeyError) as error:
        print(ERROR_PREFIX + str(error), file=sys.stderr)
        return 2


def serve_command(argv):
    """Start the local dashboard."""
    parser = argparse.ArgumentParser(description="Local task dashboard")
    parser.add_argument(COMMAND_ARGUMENT)
    parser.add_argument("--runs-dir", type=Path)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(SETTINGS_OPTION, help="Server-side workflow settings for new tasks")
    args = parser.parse_args(argv)
    from countersign.web.service import serve

    try:
        serve(args.runs_dir, args.port, settings=args.settings)
        return 0
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError) as exc:
        print(ERROR_PREFIX + str(exc), file=sys.stderr)
        return 2


def status_command(argv):
    """Display a saved run without launching a worker."""
    parser = argparse.ArgumentParser(description="Read saved run status")
    parser.add_argument(COMMAND_ARGUMENT)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        index = args.run_dir / "run.json"
        state = json.loads(index.read_text())
        print(
            json.dumps(
                {key: state.get(key) for key in ("status", "stage", "summary", "changed_files")},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (OSError, ValueError) as exc:
        print(ERROR_PREFIX + str(exc), file=sys.stderr)
        return 2


def run_command(argv):
    """Launch a fresh workflow on the original roots."""
    if argv[0] == "run":
        argv = argv[1:]
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
    args = parser.parse_args(argv)
    try:
        from countersign.application.live import execute_task

        _, status = execute_task(
            args.task, args.settings, args.debug, args.run_dir, args.plan_response
        )
        return 0 if status in ("READY_FOR_REVIEW", "NO_CHANGES_REQUIRED") else 2
    except (ValueError, OSError, KeyError) as exc:
        print(ERROR_PREFIX + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
