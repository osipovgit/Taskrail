"""Create deterministic linked worktrees without modifying the original checkout."""

from pathlib import Path

from taskrail.application import worktree_default
from taskrail.core.schema import require
from taskrail.git import process

WORKTREE = "worktree"
ROOTS = "roots"


def isolation_settings(meta, options):
    """Isolation is mandatory; settings only select its storage directory."""
    require(
        "isolation" not in meta and "isolation" not in options,
        "The isolation option was removed; standalone tasks always use linked worktrees",
    )
    default = Path.home() / ".local/share/taskrail-worktrees"
    base = Path(options.get("worktree_base", default)).expanduser()
    require(base.is_absolute(), "worktree_base must be an absolute directory")
    return dict(worktree_base=base, worktrees={})


def isolate(config, name):
    """Validate all roots before creating the first branch; delivery phases inherit roots."""
    if not worktree_default.wanted(config):
        return
    base = config["worktree_base"] / name
    roots = config[ROOTS].values()
    require(
        not any(base.is_relative_to(root) for root in roots),
        "worktree_base must be outside the declared roots",
    )
    for root in roots:
        require(
            worktree_default.isolatable(root),
            f"Worktree isolation needs a Git repository top-level with a commit: {root}",
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
        entry = worktrees.get(alias, {})
        sources[alias] = entry.get("original_source", entry.get("source", path))
    return root_entries(sources)


def root_entries(roots):
    """Alias/path entries as the browser form submits them."""
    entries = []
    for alias, path in roots.items():
        entries.append(dict(alias=alias, path=str(path)))
    return entries
