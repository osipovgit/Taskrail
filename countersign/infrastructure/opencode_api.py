"""Select the opencode CLI generation; 2.x runs behind the 1.x-compatible adapter."""

import contextlib
import json
import re
import subprocess
import sys
from pathlib import Path

from countersign.infrastructure import opencode_cli, opencode_server
from countersign.infrastructure.profile_rules import permission_worktree

ONE_X = "1.x"
TWO_X = "2.x"
AUTO = "auto"
VERSION_SECONDS = 30
VERSION = re.compile(r"\s*(?:opencode\s+)?v?(\d+)\.\d+\.\d+\S*\s*")
# Runs from the project directory, so the package root is passed explicitly.
PACKAGE_ROOT = str(Path(__file__).resolve().parents[2])
ADAPTER = (
    "import sys; sys.path.insert(0, sys.argv.pop(1)); "
    "from countersign.infrastructure.opencode_server import main; sys.exit(main())"
)


def select(setting, command):
    """An explicit generation wins; auto trusts only an exact version line."""
    if setting in {ONE_X, TWO_X}:
        return setting
    if setting != AUTO:
        raise ValueError('settings.opencode_version must be "auto", "1.x" or "2.x"')
    try:
        completed = subprocess.run(
            [*command, "--version"],
            env=opencode_cli.environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=VERSION_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ONE_X
    match = VERSION.fullmatch(completed.stdout.strip().partition("\n")[0])
    return TWO_X if match and int(match.group(1)) >= 2 else ONE_X


def launch_command(command, version):
    if version == ONE_X:
        return command
    return [sys.executable, "-I", "-c", ADAPTER, PACKAGE_ROOT, json.dumps(command)]


def stage_server(command, workspace, allow, compact=True):
    """2.x turns of one stage share a private server; 1.x launches need none."""
    if ADAPTER not in command:
        return contextlib.nullcontext()
    target = json.loads(command[-1])
    environment = opencode_cli.environment(allow, compact)
    return opencode_server.Server(target, str(workspace), env=environment)


def relative_base(config, roots, files):
    """1.x names resources relative to the Git worktree, 2.x to the run directory."""
    if config["permission_worktree"] is not None:
        return config["permission_worktree"]
    workspace = next(iter(roots.values()))
    if config["opencode_version"] == TWO_X:
        return workspace
    try:
        return permission_worktree(workspace)
    except ValueError:
        if files:
            raise
    return None
