"""Contained server-owned paths cannot redirect authority through filesystem aliases."""

import os
from pathlib import Path


def child(base, relative):
    """A strict descendant without symlink components; missing worker paths are valid."""
    if os.path.isabs(relative) or ".." in Path(relative).parts:
        raise ValueError("Owned path must be relative without parent traversal")
    root = os.path.abspath(base)
    prefix = root.rstrip(os.sep) + os.sep
    candidate = os.path.abspath(os.path.join(root, relative))
    if candidate == root or not candidate.startswith(prefix):
        raise ValueError("Owned path must remain inside its storage base")
    resolved = os.path.realpath(candidate)
    if not resolved.startswith(prefix) or resolved != candidate:
        raise ValueError("Owned path must not be redirected")
    return Path(resolved)
