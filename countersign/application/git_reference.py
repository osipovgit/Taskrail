"""Locate a declared root's Git control path without importing workflow validation."""

GIT_DIRECTORY = ".git"


def git_reference(root):
    """Guard Git metadata even when a declared root is a repository subdirectory."""
    if (root / GIT_DIRECTORY).exists():
        return root / GIT_DIRECTORY
    for parent in root.parents:
        if (parent / GIT_DIRECTORY).exists():
            return parent / GIT_DIRECTORY
    return root / GIT_DIRECTORY
