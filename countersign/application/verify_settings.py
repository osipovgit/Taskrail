"""Exact verification commands in server settings, subject to personal run approval.

Task files, models and imported drafts cannot add commands.
"""

from pathlib import Path

from countersign.interactions import local_policy, local_request

DEFAULT_SECONDS = 600
MAX_SECONDS = 3600
REQUIRED = frozenset(("cwd", "argv"))
ALLOWED = REQUIRED | {"timeout_seconds"}
SHAPE = (
    "Each verify_commands entry needs an absolute cwd, an argv list and optional timeout_seconds"
)


def parse_commands(options):
    """Validate the settings list before any run starts."""
    commands = options.get("verify_commands", [])
    if not isinstance(commands, list):
        raise ValueError("verify_commands must be a list")
    return [parse_command(command) for command in commands]


def parse_command(command):
    """One command: absolute cwd, explicit argv and a bounded timeout."""
    if not isinstance(command, dict):
        raise ValueError(SHAPE)
    fields = set(command)
    if not REQUIRED.issubset(fields) or fields - ALLOWED:
        raise ValueError(SHAPE)
    seconds = int(command.get("timeout_seconds", DEFAULT_SECONDS))
    return dict(
        cwd=absolute(command["cwd"]),
        argv=arguments(command["argv"]),
        timeout_seconds=max(1, min(MAX_SECONDS, seconds)),
    )


def absolute(cwd):
    """A declared root is matched by its exact absolute path."""
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        raise ValueError(SHAPE)
    return cwd


def arguments(argv):
    """Explicit nonempty strings, passed to exec without a shell."""
    if not isinstance(argv, list) or not argv:
        raise ValueError(SHAPE)
    if not all(local_request.valid_argument(argument) for argument in argv):
        raise ValueError(SHAPE)
    local_policy.validate(argv)
    return argv
