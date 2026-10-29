"""opencode launch settings and atomic file writes."""

import os
from pathlib import Path

from taskrail.infrastructure import environment as host_environment
from taskrail.infrastructure import opencode_api, opencode_cli


def launch_settings(options, base):
    """Select the opencode command, its managed profile directory and per-role models."""
    command = opencode_cli.validate_command(
        options.get("command", list(opencode_cli.DEFAULT_COMMAND))
    )
    validated = dict(
        agent_env_allow=host_environment.agent_allowlist(options.get("agent_env_allow", [])),
        models=opencode_cli.role_models(options.get("models", {})),
        tool_output_dir=tool_output_setting(options.get("tool_output_dir")),
    )
    version = opencode_api.select(
        options.get("opencode_version", opencode_api.AUTO), command, validated["agent_env_allow"]
    )
    destination = Path(options.get("agent_directory", str(opencode_cli.agent_directory())))
    return dict(
        command=opencode_api.launch_command(command, version),
        opencode_version=version,
        opencode_server=options.get("opencode_server", True) is not False,
        destination=(base / destination.expanduser()).resolve(),
        **validated,
    )


def atomic_write(path, content_bytes):
    """Replace a file atomically, creating its folder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    with pending.open("wb") as stream:
        stream.write(content_bytes)
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


def tool_output_setting(setting):
    """None for the opencode location, else an absolute directory; `~` is expanded."""
    if setting is None:
        return None
    directory = Path(setting).expanduser() if isinstance(setting, str) else None
    if directory is None or not directory.is_absolute():
        raise ValueError("settings.tool_output_dir must be an absolute directory path")
    return str(directory)
