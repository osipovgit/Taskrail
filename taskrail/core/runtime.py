"""Stable configuration discovery for installed and source-tree entry points."""

import json
import os
from pathlib import Path

from taskrail.core.version import VERSION

SOFTWARE_VERSION = VERSION

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
    path = Path(options.get("run_base", Path.home() / ".local/state/taskrail/runs"))
    path = path.expanduser()
    return path.resolve() if path.is_absolute() else (settings.parent / path).resolve()
