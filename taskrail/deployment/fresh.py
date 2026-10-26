"""Validate and remove application-owned storage for an explicit fresh install."""

import argparse
import shutil
import sys
from pathlib import Path

from taskrail.deployment.reset_history import history_roots
from taskrail.deployment.reset_paths import ResetPaths, overlaps

LOCKS = ((".local/share/taskrail", "install.lock"), (".local/state/taskrail", "live.lock"))


def prepare(home, protected):
    """Validate all evidence before any service is stopped or any file is removed."""
    inventory = ResetPaths(home)
    inventory.validate(protected)
    histories = {inventory.main[2] / "runs", inventory.history}
    for history in histories:
        for source in history_roots(history):
            if any(overlaps(source, target) for target in inventory.targets()):
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
    for target in inventory.targets():
        lock = locks.get(target)
        if lock:
            for child in target.iterdir():
                if child.name != lock:
                    remove(child)
        else:
            remove(target)


def main():
    """Revalidate after the service stops before applying the deletion inventory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check", "remove"))
    parser.add_argument("source", type=Path)
    parser.add_argument("supplied")
    arguments = parser.parse_args()
    protected = [arguments.source.resolve()]
    if arguments.supplied:
        protected.append(Path(arguments.supplied).expanduser().resolve())
    inventory = prepare(Path.home(), protected)
    if arguments.operation == "remove":
        erase(inventory)
    else:
        sys.stdout.write("Fresh installation will remove:\n")
        sys.stdout.writelines(f"  {target}\n" for target in inventory.targets())


if __name__ == "__main__":
    main()
