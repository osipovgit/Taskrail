"""Apply personally approved, stage-local read grants without enabling writers."""

import json
from pathlib import Path

from countersign.core import schema
from countersign.infrastructure.agent_sync import atomic_write

READ = "read"
ALLOW = "allow"
TOOLS = frozenset((READ, "glob", "grep", "list"))


def target(call, roots):
    """Only canonical paths within the user's declared roots are grantable."""
    schema.require(call.get("tool") in TOOLS, "Only read/search permissions can be granted here")
    arguments = call.get("input", {})
    path = Path(arguments.get("filePath") or arguments.get("path") or "")
    schema.require(path.is_absolute() and path.resolve() == path, "Use a canonical absolute path")
    ancestors = set(path.parents) | {path}
    schema.require(
        bool(ancestors.intersection(roots.values())),
        "Outside declared roots: provide an alternative inside a root",
    )
    return path


def add_rights(rights, call, path):
    """An exact read override is appended after existing deny patterns."""
    tool = call["tool"]
    if tool == READ:
        rights[READ].pop(str(path), None)
        rights[READ][str(path)] = ALLOW
    else:
        rights[tool] = ALLOW
    parent = path.parent if tool == READ else path
    rights["external_directory"].update({str(parent): ALLOW, f"{parent}/*": ALLOW})


def grant_all(environment, calls):
    """Validate the entire set before changing the generated stage profile."""
    paths = [target(call, environment["roots"]) for call in calls]
    profile = environment["profile"]
    sections = profile.read_text()[4:].split("\n---", 1)
    settings = json.loads(sections[0])
    populate(settings["permission"], calls, paths)
    atomic_write(profile, render(settings, sections[1]))


def apply_all(environment, calls):
    """Unsupported grants return explanatory feedback instead of executing anything."""
    try:
        grant_all(environment, calls)
    except ValueError as error:
        return dict(status="REJECTED", reason=str(error))
    return dict(status="GRANTED")


def populate(rights, calls, paths):
    """Apply only the prevalidated targets."""
    for call, path in zip(calls, paths):
        add_rights(rights, call, path)


def render(settings, body):
    """Preserve role instructions while replacing generated JSON permissions."""
    encoded = json.dumps(settings)
    return f"---\n{encoded}\n---{body}".encode()
