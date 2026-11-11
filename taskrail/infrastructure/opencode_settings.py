"""opencode launch settings."""

import shutil
from pathlib import Path

from taskrail.infrastructure import environment as host_environment
from taskrail.infrastructure import opencode_api, opencode_cli


def launch_settings(options, base):
    """Select the opencode command, its managed profile directory and per-role models."""
    configured = profile_settings(options, base)
    version = opencode_api.select(
        configured["opencode_version"], configured["command"], configured["agent_env_allow"]
    )
    return dict(
        configured,
        command=opencode_api.launch_command(configured["command"], version),
        opencode_version=version,
    )


def profile_settings(options, base):
    """Resolve the configured CLI and profile without executing a process."""
    command = opencode_cli.validate_command(
        options.get("command", list(opencode_cli.DEFAULT_COMMAND))
    )
    destination = Path(options.get("agent_directory", opencode_cli.agent_directory()))
    return dict(
        command=command,
        opencode_version=opencode_api.version_setting(
            options.get("opencode_version", opencode_api.AUTO)
        ),
        agent_env_allow=host_environment.agent_allowlist(options.get("agent_env_allow", [])),
        models=opencode_cli.role_models(options.get("models", {})),
        tool_output_dir=tool_output_setting(options.get("tool_output_dir")),
        opencode_server=options.get("opencode_server", True) is not False,
        destination=(base / destination.expanduser()).resolve(),
    )


def tool_output_setting(setting):
    """None for the opencode location, else an absolute directory; `~` is expanded."""
    if setting is None:
        return None
    directory = Path(setting).expanduser() if isinstance(setting, str) else None
    if directory is None or not directory.is_absolute():
        raise ValueError("settings.tool_output_dir must be an absolute directory path")
    return str(directory)


def command_paths(command):
    """Resolve the executable and absolute path arguments named in the CLI prefix."""
    executable = shutil.which(command[0])
    if executable:
        yield Path(executable).absolute()
    for argument in map(Path, command[1:]):
        if argument.is_absolute():
            yield argument
