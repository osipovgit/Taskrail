"""Retain the current and previous successful managed releases; never infer ownership."""

import json
import shutil
import sys
from pathlib import Path

from taskrail.core.files import atomic_json

MARKER = "installed.json"


def owned(path):
    """Only a real release with this installer's exact success marker can be pruned."""
    marker = path / MARKER
    directory = not path.is_symlink() and path.is_dir()
    if not directory or marker.is_symlink() or not marker.is_file():
        return False
    expected = dict(schema=1, release=path.name)
    try:
        return json.loads(marker.read_text()) == expected
    except (ValueError, OSError):
        return False


def retain(app, settings):
    """Keep explicit role sources and unrecognized directories regardless of age."""
    current = (app / "current").resolve()
    releases = sorted(
        filter(owned, (app / "releases").iterdir()),
        key=lambda path: (path / MARKER).stat().st_mtime_ns,
        reverse=True,
    )
    roles = role_source(settings, current)
    previous = next((path for path in releases if path != current), None)
    for path in releases:
        if path not in {current, previous} and not roles.resolve().is_relative_to(path):
            shutil.rmtree(path)


def role_source(settings, current):
    """A configured custom role source can keep an older release alive."""
    options = json.loads(settings.read_text())
    source = Path(options.get("agent_source", current / "taskrail/agents")).expanduser()
    return settings.parent / source


def main():
    """Called only after systemd confirms the new application is active."""
    app, settings = map(Path, sys.argv[1:])
    current = (app / "current").resolve()
    atomic_json(current / MARKER, dict(schema=1, release=current.name))
    retain(app, settings)


if __name__ == "__main__":
    main()
