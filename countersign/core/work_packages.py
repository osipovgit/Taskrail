"""Local plan steps are work packages, not separate concurrent workflows."""

from countersign.core.schema import require

IDENTIFIER = "id"


def validate(steps):
    """Require explicit ordering for shared files and shared acceptance criteria."""
    ancestors = {}
    for step in steps:
        dependencies = set(step["depends_on"])
        for dependency in step["depends_on"]:
            dependencies.update(ancestors[dependency])
        for earlier in steps:
            if earlier[IDENTIFIER] == step[IDENTIFIER]:
                break
            ensure_ordered(earlier, step, dependencies)
        ancestors[step[IDENTIFIER]] = dependencies


def ensure_ordered(earlier, step, dependencies):
    """Disjoint packages may be independent; shared obligations require sequencing."""
    shared = set(earlier["files"]) & set(step["files"])
    criteria = set(earlier["criteria"]) & set(step["criteria"])
    shared.update(criteria)
    require(
        not shared or earlier[IDENTIFIER] in dependencies,
        "Work packages sharing files or criteria need an explicit dependency",
    )
    action = earlier["action"].strip().casefold()
    require(
        action != step["action"].strip().casefold(),
        "Work packages need distinct deliverables",
    )
