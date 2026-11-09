"""Preflight source scope before Git can mutate files, index or commits."""

from pathlib import Path

from taskrail.core import prompt_texts
from taskrail.core.schema import require
from taskrail.git import (
    index_ownership,
    process,
    source_scope,
    worktree_restore,
)


def repository(root):
    """A declared subdirectory may belong to a larger Git working tree."""
    return Path(process.checked(root, ["rev-parse", "--show-toplevel"]).strip()).resolve()


def names(root, arguments):
    """Use NUL-delimited names, without rename inference or shell parsing."""
    output = process.checked(root, arguments).split("\x00")
    return [root / name for name in output if name]


def preflight(root, argv, context):
    """Predict changes before execution; a denial returns feedback without widening scope."""
    repo = context["repository"]
    allowed = context["allowed"]
    command = argv[0]
    if command in {"fetch", "push"}:
        return remote_command(argv)
    staged = names(repo, ["diff", "--cached", "--name-only", "--no-renames", "-z"])
    if context.get("reviewed") is not None:
        staged = [path for path in staged if path in context["reviewed"]]
    if command == "add":
        paths = [root / name for name in argv[2:]]
        source_scope.check_paths(paths, allowed)
        source_scope.original_clean(repo, paths, context["baseline"])
        require(
            owns_index(repo, staged, context),
            "Existing staged changes belong to the user",
        )
        source_scope.check_paths(paths + staged, allowed)
    elif command == "restore":
        return worktree_restore.prepare(root, argv, context, staged)
    elif command == "commit":
        require(
            owns_index(repo, staged, context),
            "Only an index staged by this run can be committed",
        )
        source_scope.check_paths(staged, allowed)
        context["affected_paths"] = staged
        if context.get("reviewed") is not None:
            return [
                "commit",
                "--only",
                *argv[1:],
                "--",
                *[path.relative_to(repo).as_posix() for path in staged],
            ]
    else:
        require(
            not process.checked(repo, ["status", "--porcelain"]),
            "Commit application requires a clean working tree; preserve current edits",
        )
        paths = affected(repo, argv)
        source_scope.check_paths(paths, allowed)
        context["affected_paths"] = paths
    return argv


def preserve_for_review(fingerprint, command, paths):
    """Explain why selected working files may be edited but their Git writes must wait."""
    if not paths or not fingerprint:
        return
    selected = fingerprint["files"] if command == "restore" else fingerprint
    blocked = set(selected).intersection(map(str, paths))
    if blocked:
        raise ValueError(prompt_texts.text("git.followup_review", paths=", ".join(sorted(blocked))))


def owns_index(repo, staged, context):
    """Only server finalization can adopt an explicitly reviewed inherited entry."""
    ordinary = [path for path in staged if path not in context.get("adopted", ())]
    return index_ownership.belongs(repo, ordinary, context["owned"])


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
