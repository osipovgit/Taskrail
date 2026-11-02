"""Locate a declared root's Git control path without importing workflow validation."""

from taskrail.core.git_marker import control

GIT_DIRECTORY = ".git"


def git_reference(root):
    """Guard Git metadata even when a declared root is a repository subdirectory."""
    for parent in (root, *root.parents):
        if control(parent / GIT_DIRECTORY):
            return parent / GIT_DIRECTORY
    return root / GIT_DIRECTORY
