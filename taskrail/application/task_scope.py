"""The immutable file boundary of an atomic child task."""

from pathlib import Path

from taskrail.application.planned_paths import safe_file

KEY = "task_scope"
REPLAN = "Child task needs parent replanning"


def configured(meta, roots, protected=()):
    """Only a child task may declare an exact list of writable, unprotected paths."""
    names = meta.get(KEY)
    if names is None:
        return absent(meta)
    if meta.get("phase") != "task" or not isinstance(names, list):
        raise ValueError("task_scope is only a list on a task phase")
    if meta.get("decompose"):
        raise ValueError(f"{REPLAN}: a child cannot request forced decomposition")
    normalized = [canonical(name, roots) for name in names]
    for name in normalized:
        safe_file(name, roots, protected)
    if len(set(normalized)) != len(normalized):
        raise ValueError("task_scope must contain unique files")
    return normalized


def absent(meta):
    """Ordinary runs have no child contract; a task phase must have one."""
    if meta.get("phase") == "task":
        raise ValueError(f"{REPLAN}: missing immutable task_scope")


def canonical(name, roots):
    """Translate the parent's absolute paths into the guard's alias-relative form."""
    if not isinstance(name, str):
        raise ValueError("task_scope entries must be paths")
    for alias, root in roots.items():
        if Path(name).is_absolute() and Path(name).is_relative_to(root):
            relative = Path(name).relative_to(root).as_posix()
            return f"{alias}/{relative}"
    return name


def check(plan, config):
    """A child cannot split again or expand its parent's reviewed file contract."""
    if config.get("phase") != "task":
        return
    if plan.get("decision") == "none" and not plan.get("steps"):
        return
    task_count = len(plan.get("steps", []))
    single = plan.get("decision") != "split" and task_count == 1
    if not single:
        raise ValueError(f"{REPLAN}: one atomic task is required; nested splits are forbidden")
    allowed = config.get(KEY)
    proposed = plan.get("proposed_change_files", [])
    if allowed is None or not set(proposed) <= set(allowed):
        raise ValueError(f"{REPLAN}: proposed files exceed the reviewed task_scope")
