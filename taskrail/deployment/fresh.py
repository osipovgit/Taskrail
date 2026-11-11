"""Validate and remove application-owned storage for an explicit fresh install."""

import argparse
import json
import shutil
import sys
from pathlib import Path

from taskrail.application.instruction_sources import ROLES
from taskrail.deployment.reset_history import history_roots
from taskrail.deployment.reset_paths import ResetPaths, overlaps

LOCKS = ((".local/share/taskrail", "install.lock"), (".local/state/taskrail", "live.lock"))


def prepare(home, protected, keep_config=None):
    """Validate all evidence before any service is stopped or any file is removed."""
    inventory = ResetPaths(home, keep_config)
    inventory.validate(protected)
    histories = {inventory.main[2] / "runs", inventory.history}
    for history in histories:
        for source in history_roots(history):
            if any(overlaps(source, target) for target in inventory.targets):
                raise ValueError("Reset paths overlap a declared project; no files deleted")
    return inventory


def remove(path):
    """Never follow a symlink while removing a validated entry."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def erase(inventory):
    """Preserve held lock inodes and remove only the validated inventory."""
    locks = {inventory.home / name: lock for name, lock in LOCKS}
    for target in inventory.targets:
        lock = locks.get(target)
        if lock:
            for child in target.iterdir():
                if child.name != lock:
                    remove(child)
        else:
            remove(target)
    if inventory.retained is not None:
        inventory.history_directory(inventory.retained).mkdir(parents=True, exist_ok=True)


def imported_sources(supplied):
    """A fresh import must not erase either its settings or its explicit role source."""
    source = Path(supplied).expanduser().resolve()
    protected = [source]
    roles = json.loads(source.read_text()).get("agent_source")
    if roles is not None:
        directory = source.parent / Path(roles).expanduser()
        protected.append(directory.resolve())
        protected.extend((directory / f"{role}.md").resolve() for role in ROLES)
    return protected


def validated(arguments):
    """Release, imported configuration and project roots must survive every deletion."""
    protected = [arguments.source.resolve()]
    if (
        arguments.supplied
        and arguments.keep_config
        and (Path.home() / ".config/taskrail/settings.json").is_file()
    ):
        protected.append(Path(arguments.supplied).expanduser().resolve())
    elif arguments.supplied:
        protected.extend(imported_sources(arguments.supplied))
    return prepare(Path.home(), protected, arguments.keep_config)


def main():
    """Revalidate under the lock. Exit 2 means no deletion has started."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check", "remove"))
    parser.add_argument("source", type=Path)
    parser.add_argument("supplied")
    parser.add_argument("--keep-config", type=Path, metavar="STAGED_SETTINGS")
    arguments = parser.parse_args()
    try:
        inventory = validated(arguments)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if arguments.operation == "remove":
        erase(inventory)
    else:
        sys.stdout.write("Installation will remove:\n")
        sys.stdout.writelines(f"  {target}\n" for target in inventory.targets)


if __name__ == "__main__":
    main()
