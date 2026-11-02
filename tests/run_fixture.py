"""Current-format metadata for hand-built server artifacts in regression tests."""

from taskrail.application.run_store import FORMAT, release_identity


def current_run(fields):
    """Explicit fixtures can override metadata to exercise rejected formats."""
    return {"run_format": FORMAT, "release_identity": release_identity(), **fields}
