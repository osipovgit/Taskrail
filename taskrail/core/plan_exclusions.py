"""Explicit excluded outcomes name another reviewed task as their owner."""


def problems(steps, known):
    """Reject self-owned, missing and unnamed exclusions before plan review."""
    found = []
    for step in steps:
        others = known - {step["id"]}
        excluded = step.get("not_todo", [])
        if any(not valid(entry, others) for entry in excluded):
            found.append(
                "line {}: Not ToDo needs another task ID and its result: T2: <result>".format(
                    step["line"]
                )
            )
    return found


def valid(exclusion, owners):
    """Require the complete owner ID and a nonempty behavior description."""
    owner, separator, outcome = exclusion.partition(":")
    return bool(separator and outcome.strip() and owner in owners)
