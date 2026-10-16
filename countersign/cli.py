"""One task file is the normal entry point."""

import argparse
import json
import sys
from pathlib import Path

ERROR_PREFIX = "Error: "


def main():
    argv = sys.argv[1:] or ["serve"]
    if argv[0] in ("web", "serve"):
        return serve_command(argv)
    if argv[0] == "status":
        return status_command(argv)
    if argv[0] == "resume":
        return resume_command(argv)
    return run_command(argv)


def resume_command(argv):
    """Continue through the same guarded execution path as the UI."""
    parser = argparse.ArgumentParser(
        description="Continue an interrupted run after source integrity checks"
    )
    parser.add_argument("command")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--settings")
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
    parser.add_argument("command")
    parser.add_argument("--runs-dir", type=Path)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--settings", help="Server-side workflow settings for new tasks")
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
    parser.add_argument("command")
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
        "--settings",
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
