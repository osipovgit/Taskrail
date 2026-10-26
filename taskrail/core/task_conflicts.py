"""Require an explicit dependency whenever two tasks own the same file."""

from itertools import combinations

from taskrail.core.schema import require
from taskrail.core.task_graph import ancestors

IDENTIFIER = "id"


def ordered_writes(steps):
    """Plan order alone cannot authorize two supposedly independent writers."""
    preceding = {step[IDENTIFIER]: ancestors(steps, step[IDENTIFIER]) for step in steps}
    for first, second in combinations(steps, 2):
        shared = set(first["files"]) & set(second["files"])
        ordered = depends(first, second, preceding) or depends(second, first, preceding)
        require(
            not shared or ordered,
            f"Tasks {first[IDENTIFIER]} and {second[IDENTIFIER]} share files; declare a dependency or combine their work",
        )


def depends(first, second, preceding):
    """Direct and transitive dependencies both establish the required ordering."""
    return first[IDENTIFIER] in preceding[second[IDENTIFIER]]
