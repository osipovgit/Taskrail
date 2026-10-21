"""Upstream opencode launch conventions shared by runs and permission checks."""

import os
from pathlib import Path

from countersign.infrastructure import environment as host_environment

DEFAULT_COMMAND = ("opencode",)
# The 2.x adapter keeps the untouched event stream next to the translated one.
RAW_EVENTS = "COUNTERSIGN_RAW_EVENTS"
AGENT_FOLDER = "agent"
COMMAND_ERROR = "settings.command must be an argv array"
MODELS_ERROR = "settings.models must map roles to provider/model strings"
# Error tags of opencode builds and the messages upstream 1.x reports without them.
PERMISSION_MARKERS = (
    "PermissionDenied",
    "PermissionRejected",
    "The user rejected permission to use this specific tool call",
    "The user has specified a rule which prevents you from using this specific tool call",
)


def validate_command(command):
    """A wrapper executable may adapt another compatible CLI build."""
    if not isinstance(command, list) or not command:
        raise ValueError(COMMAND_ERROR)
    if not all(isinstance(part, str) for part in command):
        raise ValueError(COMMAND_ERROR)
    return command


def role_models(configured):
    """A role without a model lets opencode choose its configured default."""
    if not isinstance(configured, dict):
        raise ValueError(MODELS_ERROR)
    if not all(isinstance(model, str) for model in configured.values()):
        raise ValueError(MODELS_ERROR)
    if "" in configured.values():
        raise ValueError(MODELS_ERROR)
    return dict(configured)


def permission_error(message):
    return any(marker in message for marker in PERMISSION_MARKERS)


def environment(allow=(), compact=True):
    """Secrets stay filtered; opencode rejects unknown flags, so updates are disabled here.

    Without compact, a session that outgrows the model fails instead of being summarized,
    and the workflow continues in a fresh session from recorded evidence.
    """
    variables = dict(host_environment.filtered(allow), OPENCODE_DISABLE_AUTOUPDATE="true")
    if not compact:
        variables["OPENCODE_DISABLE_AUTOCOMPACT"] = "true"
    return variables


def agent_directory():
    """Managed profiles go to a directory opencode loads agents from."""
    configured = os.environ.get("OPENCODE_CONFIG_DIR")
    if configured:
        return Path(configured) / AGENT_FOLDER
    return _base("XDG_CONFIG_HOME", ".config") / "opencode" / AGENT_FOLDER


def tool_output_pattern():
    """opencode appends an allow rule for its own truncated tool output."""
    return str(_base("XDG_DATA_HOME", ".local/share") / "opencode/tool-output/*")


def _base(name, fallback):
    """Follow XDG base directories as opencode does."""
    configured = os.environ.get(name)
    return Path(configured) if configured else Path.home() / fallback
