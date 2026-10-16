"""Stable configuration discovery for installed and source-tree entry points."""

import json
import os
from pathlib import Path

import countersign

SOFTWARE_VERSION = countersign.__version__

DEFAULT_TIMEOUT = 3600


def settings_path(explicit=None):
    """Prefer explicit settings, then the installed user configuration."""
    requested = explicit or os.environ.get("COUNTERSIGN_SETTINGS")
    if requested:
        return Path(requested).expanduser().resolve()
    installed = Path.home() / ".config/countersign/settings.json"
    if installed.is_file():
        return installed
    return Path(__file__).resolve().parents[2] / "settings.json"


def run_storage(settings=None, explicit=None):
    """Resolve shared CLI/UI history independently of the service working directory."""
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    settings = settings_path(settings)
    options = json.loads(settings.read_text()) if settings.is_file() else {}
    path = Path(options.get("run_base", Path.home() / ".local/state/countersign/runs"))
    path = path.expanduser()
    return path.resolve() if path.is_absolute() else (settings.parent / path).resolve()
