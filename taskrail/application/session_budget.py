"""Input sizes for diagnostics, separate from measured provider context occupancy."""

from pathlib import Path

from taskrail.application import context_windows
from taskrail.infrastructure import agent_profile


def capture(config, active):
    """Record actual input byte counts without treating them as model tokens."""
    folder, record = active
    role = agent_profile.body(folder / "agent.md")
    request = folder / "request.md"
    record["context_budget"] = dict(
        request_bytes=request.stat().st_size if request.exists() else 0,
        role_bytes=len(role.encode("utf-8")),
        attached_bytes=attachment_bytes(record),
        input_capacity_tokens=context_windows.role_capacity(config, record["role"]),
    )


def attachment_bytes(record):
    """Each --file occurrence is transmitted, including repeated paths."""
    paths = map(Path, record.get("attached_files", ()))
    return sum(path.stat().st_size for path in paths)
