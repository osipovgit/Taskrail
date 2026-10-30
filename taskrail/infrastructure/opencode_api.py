"""Select the opencode CLI generation; 2.x runs behind the 1.x-compatible adapter.

Both generations run every turn of a stage on one private server: 2.x through the
adapter, 1.x with `run --attach` where the CLI offers it (`opencode_serve`).
"""

import contextlib
import json
import re
import subprocess
import sys
from pathlib import Path

from taskrail.infrastructure import opencode_cli, opencode_serve, opencode_server
from taskrail.infrastructure.profile_rules import permission_worktree

ONE_X = "1.x"
TWO_X = "2.x"
AUTO = "auto"
VERSION_SECONDS = 30
VERSION = re.compile(
    r"\s*(?:[a-z][a-z0-9_.-]*\s+)?v?(\d+)\.\d+\.\d+(?:-[\w.-]+)?(?:\+[\w.-]+)?\s*", re.I
)
# Runs from the project directory, so the package root is passed explicitly.
PACKAGE_ROOT = str(Path(__file__).resolve().parents[2])
ADAPTER = (
    "import sys; sys.path.insert(0, sys.argv.pop(1)); "
    "from taskrail.infrastructure.opencode_server import main; sys.exit(main())"
)


def select(setting, command, allow=()):
    """An explicit generation wins; auto trusts only an exact version line."""
    if setting in {ONE_X, TWO_X}:
        return setting
    if setting != AUTO:
        raise ValueError('settings.opencode_version must be "auto", "1.x" or "2.x"')
    try:
        completed = subprocess.run(
            [*command, "--version"],
            env=opencode_cli.environment(allow),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=VERSION_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(
            "Cannot detect opencode interface; set settings.opencode_version explicitly"
        ) from error
    return detected(completed)


def detected(completed):
    """Never infer compatibility from a failed, ambiguous or unsupported version."""
    match = VERSION.fullmatch(completed.stdout.strip())
    if completed.returncode or match is None:
        raise ValueError(
            "Cannot detect opencode interface; set settings.opencode_version explicitly"
        )
    versions = {1: ONE_X, 2: TWO_X}
    major = int(match.group(1))
    if major not in versions:
        raise ValueError(f"Unsupported opencode major version: {major}; supported: 1.x, 2.x")
    return versions[major]


def launch_command(command, version):
    if version == ONE_X:
        return command
    return [sys.executable, "-I", "-c", ADAPTER, PACKAGE_ROOT, json.dumps(command)]


def stage_server(command, workspace, allow, compact=True, **options):
    """The private server every turn of one stage runs on, or None for one process a turn.

    options: startup, the readiness deadline and Stop check, and attach, False to keep
    one 1.x process a turn.
    """
    environment = opencode_cli.environment(allow, compact)
    startup = options.get("startup")
    if ADAPTER not in command:
        attach = options.get("attach", True) and bool(command)
        if not (attach and opencode_serve.supported(command, workspace, environment)):
            return contextlib.nullcontext()
        return opencode_serve.StageServer(command, str(workspace), environment, startup)
    target = json.loads(command[-1])
    server = opencode_server.Server(target, str(workspace), env=environment)
    if startup is not None:
        server.startup.update(startup)
        server.startup["timeout"] = min(server.startup["timeout"], opencode_server.READY_SECONDS)
    return server


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
