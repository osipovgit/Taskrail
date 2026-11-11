"""Stable configuration discovery for installed and source-tree entry points."""

import json
import os
from pathlib import Path

DEFAULT_TIMEOUT = 3600


def settings_path(explicit=None):
    """Prefer explicit settings, then the installed user configuration."""
    requested = explicit or os.environ.get("TASKRAIL_SETTINGS")
    if requested:
        return Path(requested).expanduser().resolve()
    installed = Path.home() / ".config/taskrail/settings.json"
    if installed.is_file():
        return installed
    return Path(__file__).resolve().parents[1] / "settings.json"


def run_storage(settings=None, explicit=None):
    """Resolve shared CLI/UI history independently of the service working directory."""
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    settings = settings_path(settings)
    options = json.loads(settings.read_text()) if settings.is_file() else {}
    return configured_storage(options, settings.parent)


def configured_storage(options, base):
    """Resolve run storage against the directory owning the effective settings."""
    path = Path(options.get("run_base", Path.home() / ".local/state/taskrail/runs"))
    return (base / path.expanduser()).resolve()
