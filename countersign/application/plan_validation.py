"""Normalize planner paths and check a ready plan against task boundaries."""

from pathlib import Path

from countersign.application import planned_checks, task_scope
from countersign.application.planned_paths import safe_file
from countersign.core import control, protected_paths
from countersign.core.paths import readable_source

PLAN_PATHS = ("files_read", "proposed_change_files")
UNIQUE_NAMES = "Plan needs unique proposed_change_files"


def canonical_plan(plan, roots):
    """Accept in-root absolute paths in planner arrays; store alias paths internally."""
    for field in PLAN_PATHS:
        entries = plan.get(field)
        if isinstance(entries, list):
            plan[field] = [alias_path(name, roots) for name in entries]
    return plan


def alias_path(name, roots):
    """Convert an absolute in-root path; keep anything else for validation."""
    if not isinstance(name, str) or not Path(name).is_absolute():
        return name
    for alias, root in roots.items():
        if Path(name).is_relative_to(root):
            relative = Path(name).relative_to(root).as_posix()
            return f"{alias}/{relative}"
    return name


def validate_plan(plan, roots, task, config=None):
    """Planned edits must be unique, safe and never touch the task file."""
    if plan["status"] != "PLAN_READY":
        return
    control.check_plan(plan, config or {})
    task_scope.check(plan, config or {})
    planned_checks.validate(plan, config or {})
    proposed = unique_names(plan.get("proposed_change_files"))
    control.check_reads(plan.get("files_read"), plan.get("evidence"))
    protected = protected_paths.patterns(config or {})
    targets = [safe_file(name, roots, protected) for name in proposed]
    for name in plan["files_read"]:
        readable_source(name, roots)
    if task in targets:
        raise ValueError("Task specification must not be edited")


def unique_names(names):
    """Require a list of distinct strings."""
    if not isinstance(names, list):
        raise ValueError(UNIQUE_NAMES)
    texts = [name for name in names if isinstance(name, str)]
    if len(set(texts)) != len(names):
        raise ValueError(UNIQUE_NAMES)
    return names
