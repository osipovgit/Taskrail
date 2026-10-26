"""The dependency graph of planned tasks: checks and execution order.

Tasks run in topological order; among tasks that are ready at the same time, the
plan's order decides.
"""

from countersign.core.schema import require

IDENTIFIER = "id"
DEPENDS = "depends_on"


def order(steps):
    """Task IDs in execution order; ValueError for unknown, self or cyclic dependencies."""
    waiting = {step[IDENTIFIER]: set(step[DEPENDS]) for step in steps}
    check_references(waiting)
    ordered = []
    while waiting:
        ready = ready_tasks(waiting, ordered)
        if not ready:
            raise ValueError(f"Tasks depend on each other in a cycle: {cycle(waiting)}")
        ordered.append(ready[0])
        waiting.pop(ready[0])
    return ordered


def ready_tasks(waiting, ordered):
    """The waiting tasks whose dependencies all ran, in plan order."""
    done = set(ordered)
    return [name for name, needs in waiting.items() if needs <= done]


def check_references(waiting):
    """Every dependency names another planned task."""
    for name, needs in waiting.items():
        known = needs <= set(waiting) and name not in needs
        require(known, f"{name} depends on an unknown task or itself")


def cycle(waiting):
    """One dependency cycle among the waiting tasks, as T1 -> T2 -> T1."""
    path = [next(iter(waiting))]
    while path.count(path[-1]) < 2:
        needs = sorted(waiting[path[-1]] & set(waiting))
        path.append(needs[0])
    return " -> ".join(path[path.index(path[-1]) :])


def ancestors(steps, name):
    """Every direct and transitive prerequisite of a task."""
    needs = {step[IDENTIFIER]: step[DEPENDS] for step in steps}
    found = set()
    pending = list(needs[name])
    while pending:
        current = pending.pop()
        if current not in found:
            found.add(current)
            pending.extend(needs[current])
    return found
