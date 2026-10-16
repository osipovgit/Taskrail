"""Detached CLI-equivalent worker. The workflow retains its global execution lock."""

import argparse
import json
import os
import sys
from pathlib import Path

from countersign.application.live import execute_task
from countersign.core.files import atomic_json


def arguments():
    """Parse the trusted worker launch arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("submission", type=Path)
    parser.add_argument("run", type=Path)
    parser.add_argument("--settings")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--extend-budget", action="store_true")
    return parser.parse_args()


def main():
    args = arguments()
    manifest = args.submission / "launch.json"
    state = json.loads(manifest.read_text(encoding="utf-8"))
    state.update(status="RUNNING", pid=os.getpid(), summary="The worker is running.")
    atomic_json(manifest, state)
    try:
        task = args.run / "00-input/task.md" if args.resume else args.submission / "task.md"
        _, status = execute_task(
            task,
            args.settings,
            run_dir=args.run,
            resume="extend" if args.extend_budget else args.resume,
        )
        state.update(status=status, summary="Task finished. See the run report.")
    except KeyboardInterrupt:
        state.update(status="INTERRUPTED", summary="Worker interrupted; partial work is preserved.")
    except Exception as error:
        state.update(status="LAUNCH_ERROR", summary=str(error))
        print("Worker error: " + str(error), flush=True)
    finally:
        atomic_json(manifest, state)
    return 0 if state["status"] in ("READY_FOR_REVIEW", "NO_CHANGES_REQUIRED") else 2


if __name__ == "__main__":
    sys.exit(main())
