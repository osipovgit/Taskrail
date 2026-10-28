"""Isolation: a run edits new linked Git worktrees on their own branches.

By default (`auto`, see `worktree_default`) a code change in Git repositories gets
them. The source checkout is never touched;
approved tasks are committed on the branches, nothing is merged or removed
automatically, and the report says where the changes are.
"""

from pathlib import Path

from taskrail.application import worktree_default
from taskrail.core.schema import require
from taskrail.git import process

MODES = ("in_place", "worktree", "auto")
WORKTREE = "worktree"
AUTO = "auto"
ROOTS = "roots"


def isolation_settings(meta, options, run_base):
    """The task chooses isolation; server settings choose where worktrees live."""
    mode = meta.get("isolation", AUTO)
    if mode not in MODES:
        raise ValueError("isolation must be in_place, worktree or auto")
    base = Path(options.get("worktree_base", run_base.parent / "worktrees")).expanduser()
    if not base.is_absolute():
        raise ValueError("worktree_base must be an absolute directory")
    isolation = None if mode == AUTO else mode == WORKTREE
    return dict(isolation=isolation, worktree_base=base, worktrees={})


def isolate(config, name):
    """Create one worktree per root from its HEAD and run against the worktrees.

    Nothing happens when the task chose in place or the default does not apply.
    """
    if not worktree_default.wanted(config):
        return
    base = config["worktree_base"] / name
    roots = config[ROOTS].values()
    require(
        not any(base.is_relative_to(root) for root in roots),
        "worktree_base must be outside the declared roots",
    )
    record = {}
    for alias, root in config[ROOTS].items():
        record[alias] = create(root, base / alias, name)
    adopt(config, record)


def create(root, path, name):
    """`git worktree add` with hooks and repository filters disabled."""
    top = process.checked(root, ["rev-parse", "--show-toplevel"]).strip()
    require(Path(top).resolve() == root, "Worktree isolation needs repository top-level roots")
    head = process.checked(root, ["rev-parse", "--verify", "HEAD"]).strip()
    branch = f"taskrail/{name}"
    checkout(root, ["worktree", "add", "-b", branch, str(path), head])
    location = str(path.resolve())
    return dict(source=str(root), worktree=location, branch=branch, base=head)


def checkout(root, arguments):
    """Repository filters could run commands while files are checked out."""
    outcome = process.invoke(root, arguments, process.filter_settings(root))
    require(outcome.returncode == 0, outcome.stderr or "git worktree add failed")


def adopt(config, record):
    """Effective roots are the worktrees; relative permission names use the first one."""
    roots = {}
    for alias, entry in record.items():
        roots[alias] = Path(entry[WORKTREE])
    config[ROOTS] = roots
    config["permission_worktree"] = next(iter(roots.values()))
    config["worktrees"] = record


def source_roots(index):
    """Root entries of a run index with each isolated worktree mapped to its source."""
    worktrees = index.get("worktrees") or {}
    sources = {}
    for alias, path in index[ROOTS].items():
        sources[alias] = worktrees.get(alias, {}).get("source", path)
    return root_entries(sources)


def root_entries(roots):
    """Alias/path entries as the browser form submits them."""
    entries = []
    for alias, path in roots.items():
        entries.append(dict(alias=alias, path=str(path)))
    return entries
