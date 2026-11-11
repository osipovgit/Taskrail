"""Validate and remove application-owned storage for an explicit fresh install."""

import argparse
import shutil
import sys
from pathlib import Path

from taskrail.application.instruction_sources import ROLES
from taskrail.deployment.reset_history import history_roots
from taskrail.deployment.reset_paths import ResetPaths, overlaps
from taskrail.deployment.settings_stage import read_settings
from taskrail.infrastructure.opencode_cli import validate_command
from taskrail.infrastructure.opencode_settings import command_paths

LOCKS = ((".local/share/taskrail", "install.lock"), (".local/state/taskrail", "live.lock"))


def prepare(home, protected, incoming=None, profile_directory=None):
    """Validate all evidence before any service is stopped or any file is removed."""
    inventory = ResetPaths(home, profile_directory)
    inventory.validate(protected, incoming or {})
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


def imported_sources(supplied, incoming):
    """A fresh import must not erase either its settings or its explicit role source."""
    specified = Path(supplied).expanduser().absolute()
    source = specified.resolve()
    protected = [specified, source]
    if incoming.get("agent_source") == str(Path.home() / ".config/taskrail/agents"):
        roles = read_settings(source).get("agent_source")
        if not isinstance(roles, str) or not roles:
            raise ValueError(f"Supplied settings no longer name the imported role source: {source}")
        directory = source.parent / Path(roles).expanduser()
        protected.extend((directory, directory.resolve()))
        protected.extend((directory / f"{role}.md").resolve() for role in ROLES)
    return protected


def validated(arguments):
    """Release, imported configuration and project roots must survive every deletion."""
    protected = [arguments.source.resolve()]
    incoming = read_settings(arguments.incoming_settings)
    for path in command_paths(validate_command(incoming.get("command"))):
        protected.extend((path, path.resolve()))
    if arguments.supplied:
        protected.extend(imported_sources(arguments.supplied, incoming))
    return prepare(Path.home(), protected, incoming, arguments.profile_directory)


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check", "remove"))
    parser.add_argument("source", type=Path)
    parser.add_argument("supplied")
    parser.add_argument("--incoming-settings", required=True, type=Path, metavar="STAGED_SETTINGS")
    parser.add_argument("--profile-directory", type=Path)
    return parser


def main():
    """Revalidate under the lock. Exit 2 means no deletion has started."""
    parser = argument_parser()
    arguments = parser.parse_args()
    try:
        inventory = validated(arguments)
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))
    else:
        if arguments.operation == "remove":
            erase(inventory)
        else:
            sys.stdout.write("Installation will remove:\n")
            sys.stdout.writelines(f"  {target}\n" for target in inventory.targets)


if __name__ == "__main__":
    main()
