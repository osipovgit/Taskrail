"""Shared source boundaries for citations, repair delivery and readable views."""


def roots(run, path, declared):
    """Run-owned evidence never inherits access from an overlapping project root."""
    if run not in path.parents:
        return declared
    return {
        name: run / "00-input" / name
        for name in ("git", "ssh", "local", "checks", "preimages", "original", "dependency-checks")
    }
