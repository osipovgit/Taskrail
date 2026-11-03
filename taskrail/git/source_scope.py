"""Shared source authorization checks for Git mutations and their recorded effects."""

from taskrail.core.schema import require
from taskrail.git import history_outcome, staging_baseline


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
