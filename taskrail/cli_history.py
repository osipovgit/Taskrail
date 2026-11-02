"""Archive unsupported run histories without reading their obsolete payload shapes."""

import argparse
import json
import sys
from pathlib import Path

from taskrail.application import run_locks, run_store
from taskrail.core.runtime import run_storage
from taskrail.web.lifecycle import trash_run


def archive_old(base):
    """Serialize against workers and installers; move only unsupported direct children."""
    archived = []
    with run_locks.lock_file(Path.home() / run_locks.STATE / run_locks.INSTALL_LOCK) as lock:
        if not run_locks.locked(lock, run_locks.EXCLUSIVE):
            raise ValueError("Stop active tasks before archiving old history")
        for run in old_runs(base):
            trash_run(base, run, archive=True)
            archived.append(run.name)
    return archived


def old_runs(base):
    """Enumerate old indices without interpreting their task or evidence artifacts."""
    if not base.exists():
        return
    for run in sorted(base.iterdir()):
        index = run / "run.json"
        if not candidate(run, index):
            continue
        if index.is_symlink():
            raise ValueError("Run index must not be a symlink")
        if not run_store.supported(json.loads(index.read_text())):
            yield run


def candidate(run, index):
    """Only direct real run directories with an index belong to history."""
    visible = not run.name.startswith(".") and not run.is_symlink()
    return visible and index.is_file()


def main(argv=None):
    """The public CLI and installer use the same history operation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("archive-old",))
    parser.add_argument("--settings")
    parser.add_argument("--runs-dir")
    args = parser.parse_args(argv)
    archived = archive_old(run_storage(args.settings, args.runs_dir))
    sys.stdout.write(f"{json.dumps(dict(archived=archived))}\n")
