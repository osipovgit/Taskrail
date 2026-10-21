"""A requirement split between tasks must name a distinct scope for every part."""

IDENTIFIER = "id"


def problems(owners, requirements):
    """One problem per requirement whose parts are not told apart by scope."""
    found = []
    for name, split in collect(owners).items():
        if ambiguous(split):
            found.append(message(name, split, requirements))
    return found


def collect(owners):
    """Requirement ID -> its parts, each with the task that owns it."""
    parts = {}
    for task, owned in owners.items():
        for entry in owned:
            part = dict(entry, task=task)
            parts.setdefault(part[IDENTIFIER], []).append(part)
    return parts


def ambiguous(split):
    """Several owners, and a part without a scope or two parts with the same one."""
    scopes = [entry["scope"] for entry in split]
    distinct = len(set(scopes)) == len(scopes)
    return len(split) > 1 and not (all(scopes) and distinct)


def message(name, split, requirements):
    """The problem for one requirement, named by its plan label."""
    number = [entry[IDENTIFIER] for entry in requirements].index(name) + 1
    tasks = ", ".join(entry["task"] for entry in split)
    return f"R{number} is split between {tasks}: give each part a distinct [scope]"
