"""Setup, status and service subcommands."""

import argparse
import json
import sys
from pathlib import Path

ERROR_PREFIX = "Error: "
SETTINGS_OPTION = "--settings"
COMMAND_ARGUMENT = "command"
DEFAULT_PORT = 8787
STATUS_FIELDS = ("status", "stage", "summary", "changed_files")


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


def serve_command(argv):
    """Start the local dashboard; Ctrl+C stops it cleanly."""
    parser = argparse.ArgumentParser(description="Local task dashboard")
    parser.add_argument(COMMAND_ARGUMENT)
    parser.add_argument("--runs-dir", type=Path)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(SETTINGS_OPTION, help="Server-side workflow settings for new tasks")
    args = parser.parse_args(argv)
    from countersign.web.service import serve

    try:
        serve(args.runs_dir, args.port, settings=args.settings)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError) as error:
        sys.stderr.write(f"{ERROR_PREFIX}{error}\n")
        return 2
    return 0


def status_command(argv):
    """Display a saved run without launching a worker."""
    parser = argparse.ArgumentParser(description="Read saved run status")
    parser.add_argument(COMMAND_ARGUMENT)
    parser.add_argument("run_dir", type=Path)
    index = parser.parse_args(argv).run_dir / "run.json"
    try:
        state = json.loads(index.read_text())
    except (OSError, ValueError) as error:
        sys.stderr.write(f"{ERROR_PREFIX}{error}\n")
        return 2
    summary = json.dumps(
        {key: state.get(key) for key in STATUS_FIELDS}, ensure_ascii=False, indent=2
    )
    sys.stdout.write(f"{summary}\n")
    return 0
