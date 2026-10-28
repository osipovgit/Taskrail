"""Setup, status and service subcommands."""

import argparse
import json
import sys
from pathlib import Path

ERROR_PREFIX = "Error: "
SETTINGS_OPTION = "--settings"
COMMAND_ARGUMENT = "command"
DEFAULT_PORT = 8787


def check_command(argv):
    """Verify settings, the opencode CLI, permission enforcement and run storage."""
    parser = argparse.ArgumentParser(description=check_command.__doc__)
    parser.add_argument(COMMAND_ARGUMENT)
    parser.add_argument(SETTINGS_OPTION)
    from taskrail.application import yaml_install
    from taskrail.infrastructure import sandbox
    from taskrail.onboarding import check

    lines = check(parser.parse_args(argv).settings)
    lines.extend((yaml_install.health(), sandbox.health()))
    failures = 0
    for passed, message in lines:
        failures += not passed
        sys.stdout.write("{} {}\n".format("OK  " if passed else "FAIL", message))
    return 1 if failures else 0


def init_command(argv):
    """Create ~/.config/taskrail/settings.json; prompts on a terminal for missing values."""
    parser = argparse.ArgumentParser(description=init_command.__doc__)
    parser.add_argument(COMMAND_ARGUMENT)
    parser.add_argument("--opencode", help="opencode command, default: opencode on PATH")
    parser.add_argument("--model", action="append", default=[], help="ROLE=provider/model")
    parser.add_argument("--format-repair-tools", choices=("none", "read"))
    parser.add_argument("--force", action="store_true", help="Replace existing settings")
    args = parser.parse_args(argv)
    from taskrail.onboarding import init

    try:
        target = init(args.opencode, args.model, args.format_repair_tools, force=args.force)
    except (OSError, ValueError) as error:
        sys.stderr.write(f"{ERROR_PREFIX}{error}\n")
        return 2
    sys.stdout.write(f"Wrote {target}. Run: taskrail check\n")
    return 0


def serve_command(argv):
    """Start the local dashboard; Ctrl+C stops it cleanly."""
    parser = argparse.ArgumentParser(description="Local task dashboard")
    parser.add_argument(COMMAND_ARGUMENT)
    parser.add_argument("--runs-dir", type=Path)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(SETTINGS_OPTION, help="Server-side workflow settings for new tasks")
    args = parser.parse_args(argv)
    from taskrail.web.service import serve

    try:
        serve(args.runs_dir, args.port, settings=args.settings)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError) as error:
        sys.stderr.write(f"{ERROR_PREFIX}{error}\n")
        return 2
    return 0


def analytics_command(argv):
    """Print totals across all runs as JSON."""
    parser = argparse.ArgumentParser(description="Totals across all runs")
    parser.add_argument(COMMAND_ARGUMENT)
    parser.add_argument(SETTINGS_OPTION)
    parser.add_argument("--runs-dir", type=Path)
    args = parser.parse_args(argv)
    from taskrail.core.runtime import run_storage
    from taskrail.web.analytics import analytics

    totals = analytics(run_storage(args.settings, args.runs_dir))
    report = json.dumps(totals, ensure_ascii=False, indent=2)
    sys.stdout.write(f"{report}\n")
    return 0
