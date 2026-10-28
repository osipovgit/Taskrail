"""Preflight source scope before Git can mutate files, index or commits."""

from pathlib import Path

from taskrail.core.schema import require
from taskrail.git import history_outcome, index_ownership, process, staging_baseline


def repository(root):
    """A declared subdirectory may belong to a larger Git working tree."""
    return Path(process.checked(root, ["rev-parse", "--show-toplevel"]).strip()).resolve()


def names(root, arguments):
    """Use NUL-delimited names, without rename inference or shell parsing."""
    output = process.checked(root, arguments).split("\x00")
    return [root / name for name in output if name]


def check_paths(paths, allowed):
    """Never turn repository-relative names into access outside approved source files."""
    require(bool(paths), "Git operation has no affected source files")
    for path in paths:
        require(path.resolve() == path and ".git" not in path.parts, "Unsafe Git source path")
        require(
            not path.is_dir() and not path.is_symlink(),
            "Git must not introduce directory or symlink edit targets",
        )
        require(path in allowed, f"Git operation affects a file outside approved scope: {path}")


def original_clean(repo, paths, baseline):
    """Do not stage unrelated pre-existing edits, even inside an approved file."""
    revision = history_outcome.head(repo, unborn=True)
    for path in paths:
        original = baseline.get(str(path))
        committed = staging_baseline.committed(repo, path, revision) if revision else None
        if original is None:
            require(committed is None, "Missing baseline for an existing tracked file")
        else:
            require(
                committed is not None,
                "Pre-existing untracked file cannot be committed automatically",
            )
            require(
                staging_baseline.source_identity(original)
                == staging_baseline.source_identity(committed),
                "Preserve pre-existing user edits; Git staging requires a clean original file",
            )


def preflight(root, argv, context):
    """Predict changes before execution; a denial returns feedback without widening scope."""
    repo = context["repository"]
    allowed = context["allowed"]
    command = argv[0]
    if command in {"fetch", "push"}:
        return remote_command(argv)
    staged = names(repo, ["diff", "--cached", "--name-only", "--no-renames", "-z"])
    if command == "add":
        paths = [root / name for name in argv[2:]]
        check_paths(paths, allowed)
        original_clean(repo, paths, context["baseline"])
        require(
            index_ownership.belongs(repo, staged, context["owned"]),
            "Existing staged changes belong to the user",
        )
        check_paths(paths + staged, allowed)
    elif command == "commit":
        require(
            index_ownership.belongs(repo, staged, context["owned"]),
            "Only an index staged by this run can be committed",
        )
        check_paths(staged, allowed)
        context["affected_paths"] = staged
    else:
        require(
            not process.checked(repo, ["status", "--porcelain"]),
            "Commit application requires a clean working tree; preserve current edits",
        )
        paths = affected(repo, argv)
        check_paths(paths, allowed)
        context["affected_paths"] = paths
    return argv


def affected(repo, argv):
    """Merge only fast-forwards; commit application excludes merge commits."""
    revision = argv[-1]
    if argv[0] == "merge":
        process.checked(repo, ["merge-base", "--is-ancestor", "HEAD", revision])
        return names(repo, ["diff", "--name-only", "--no-renames", "-z", "HEAD", revision])
    parents = process.checked(repo, ["rev-list", "--parents", "-n", "1", revision]).split()
    require(len(parents) <= 2, "Merge commits require an explicit supported parent policy")
    return names(
        repo,
        [
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "--no-renames",
            "-r",
            "-z",
            revision,
        ],
    )


def remote_command(argv):
    """Do not inherit force refspecs, mirror push or custom remote executables."""
    if argv[0] == "fetch":
        return ["fetch", "--no-tags", argv[1], f"refs/heads/*:refs/remotes/{argv[1]}/*"]
    return argv
