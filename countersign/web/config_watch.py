"""Observe persistent settings; workers load a fresh snapshot at task startup."""

import hashlib
import json
import logging
from pathlib import Path


def fingerprint(settings):
    """Track settings and role content without logging any configuration secrets."""
    raw = settings.read_bytes()
    options = json.loads(raw)
    if not isinstance(options, dict):
        raise ValueError("Settings must be an object")
    folder = Path(options.get("agent_source", settings.parent / "agents")).expanduser()
    if not folder.is_absolute():
        folder = settings.parent / folder
    digest = hashlib.sha256(raw)
    for path in sorted(folder.glob("*.md")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class ConfigurationWatch:
    """Report changes once; never mutate the active worker's frozen settings."""

    def __init__(self, settings):
        self.settings = settings
        self.previous = None

    def poll(self):
        """Invalid intermediate edits do not crash the running application."""
        try:
            current = fingerprint(self.settings)
        except (OSError, ValueError, TypeError):
            current = "invalid"
        if current == self.previous:
            return
        if current == "invalid":
            logging.warning("Settings or agents unreadable; correct them before starting a task")
        elif self.previous is not None:
            logging.info(
                "Configuration changed: new tasks load new settings and agents; "
                "active tasks retain snapshots. Restart the service for run_base/port changes."
            )
        self.previous = current
