"""Runs on Taskrail's own Git branches: a task may go beyond its plan.

A run in isolated worktrees, and every task of its split, works on `taskrail/<run>`
branches that hold only the run's own work, committed task by task (`task_commit`).
There the planned files are the expected scope, not a limit: a file the implementer
changes beyond them is adopted with its preimage from the branch's last commit, where
the task started. Protected and unsafe files are never adopted.
"""

from pathlib import Path

from taskrail.application import lock_resources
from taskrail.application.planned_paths import safe_file
from taskrail.application.worktree_default import top_level
from taskrail.core import protected_paths
from taskrail.core.files import changed
from taskrail.core.schema import require
from taskrail.git import process
from taskrail.infrastructure.agent_sync import atomic_write

KEY = "task_branch"
BEYOND = "beyond_plan"
PREIMAGES = "preimages"


def detect(roots, records):
    """Only authenticated server-created worktrees grant automatic task finalization."""
    if not records:
        return False
    require(set(roots) == set(records), "Owned worktree roots differ")
    for alias, root in roots.items():
        require(on_branch(root, records[alias]), "Owned worktree identity changed")
    return bool(roots)


def on_branch(root, record):
    """Check the recorded directory, branch and shared repository, never a name prefix."""
    source = Path(record["source"])
    located = root == Path(record["worktree"]) and source != root
    if not located or not top_level(root):
        return False
    branch = process.invoke(root, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    shared = lock_resources.identity(root)
    return (
        branch.returncode == 0
        and branch.stdout.strip() == record["branch"]
        and shared is not None
        and shared == lock_resources.identity(source)
    )


def extend(workflow):
    """Adopt the implementer's changes beyond the plan, with preimages from the branch."""
    allowed = workflow.flow["allowed"]
    originals = workflow.state[PREIMAGES]
    for name in changed(workflow.guard.before, workflow.guard.scan()):
        if name not in allowed and adoptable(workflow.config, name):
            if name not in originals:
                originals[name] = preimage(workflow.run, workflow.config["roots"], name)
            allowed.append(name)
            workflow.state.setdefault(BEYOND, []).append(name)


def adoptable(config, name):
    """A safe source file that is not protected; anything else keeps failing the scope check."""
    try:
        safe_file(name, config["roots"], protected_paths.patterns(config))
    except ValueError:
        return False
    return True


def preimage(run, roots, name):
    """Store the file's bytes at the branch's last commit; None for a new file."""
    alias, relative = name.split("/", 1)
    committed_bytes = process.blob(roots[alias], f"HEAD:{relative}")
    if committed_bytes is None:
        return None
    reference = f"00-input/preimages/{name}"
    atomic_write(run / reference, committed_bytes)
    return reference
