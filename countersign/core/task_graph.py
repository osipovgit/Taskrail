"""The dependency graph of planned tasks: checks, execution order and waves.

Tasks run in topological order; among tasks that are ready at the same time, the
plan's order decides. A wave holds the tasks whose longest dependency chain has the
same length, so the tasks of one wave do not depend on each other.
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
            raise ValueError("Tasks depend on each other in a cycle: {0}".format(cycle(waiting)))
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


def waves(steps):
    """Task ID -> wave number, 1 for tasks without dependencies."""
    needs = {step[IDENTIFIER]: step[DEPENDS] for step in steps}
    levels = {}
    for name in order(steps):
        earlier = [levels[need] for need in needs[name]]
        levels[name] = 1 + max(earlier, default=0)
    return levels


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


def plan_order(plan):
    """The order of a stored plan's tasks, or [] without a plan or tasks."""
    if not plan or not plan.get("steps"):
        return []
    return order(plan["steps"])
