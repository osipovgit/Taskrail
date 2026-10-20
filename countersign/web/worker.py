"""Detached CLI-equivalent worker; the workflow holds the locks of its projects and run."""

import argparse
import json
import os
import sys
from pathlib import Path

from countersign.application.live import execute_task
from countersign.core.files import atomic_json
from countersign.observability.progress import say

SUCCESS = frozenset(("READY_FOR_REVIEW", "NO_CHANGES_REQUIRED", "TASKS_READY"))


def arguments():
    """Parse the trusted worker launch arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("submission", type=Path)
    parser.add_argument("run", type=Path)
    parser.add_argument("--settings")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--extend-budget", action="store_true")
    parser.add_argument("--note-file", type=Path)
    return parser.parse_args()


def main():
    """Record the worker in the launch manifest and run the task."""
    args = arguments()
    manifest = args.submission / "launch.json"
    state = json.loads(manifest.read_text(encoding="utf-8"))
    state.update(status="RUNNING", pid=os.getpid(), summary="The worker is running.")
    atomic_json(manifest, state)
    try:
        state.update(run_task(args))
    except KeyboardInterrupt:
        state.update(status="INTERRUPTED", summary="Worker interrupted; partial work is preserved.")
    except Exception as error:
        state.update(status="LAUNCH_ERROR", summary=str(error))
        say(f"Worker error: {error}")
    finally:
        atomic_json(manifest, state)
    return 0 if state["status"] in SUCCESS else 2


def run_task(args):
    """Run a new task, or continue the run with its frozen task file."""
    task = args.run / "00-input/task.md" if args.resume else args.submission / "task.md"
    note = args.note_file.read_text(encoding="utf-8") if args.note_file else None
    options = dict(run_dir=args.run, note=note)
    options["resume"] = "extend" if args.extend_budget else args.resume
    status = execute_task(task, args.settings, **options)[1]
    return dict(status=status, summary="Task finished. See the run report.")


if __name__ == "__main__":
    sys.exit(main())
